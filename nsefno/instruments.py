"""Instrument master: normalised contract list + a resolver for trader-style text.

Lot size, tick size, freeze quantity and expiry are taken ONLY from the master loaded
for the current day - never from constants (NIFTY went 75 -> 65 from the Jan-2026
series; SENSEX is 25 at the time of writing; these numbers keep changing).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from . import resources
from .errors import InstrumentNotFound


@dataclass(frozen=True, slots=True)
class Instrument:
    exchange: str            # NFO | BFO (derivatives segment code)
    underlying: str          # NIFTY, BANKNIFTY, SENSEX ...
    instrument_type: str     # CE | PE | FUT
    expiry: dt.date
    strike: float            # 0 for futures
    lot_size: int
    tick_size: float
    tradingsymbol: str
    token: str               # broker/exchange token
    freeze_qty: int | None = None      # exchange freeze figure: orders must be STRICTLY below it
    source: str = ""
    max_order_qty: int | None = None   # broker-published max quantity per order (inclusive)
    extra: tuple = ()                  # broker-specific fields as (key, value) pairs

    def get(self, key: str, default=None):
        return dict(self.extra).get(key, default)

    @property
    def order_qty_cap(self) -> int | None:
        """Largest allowed quantity in one order (inclusive), from either convention."""
        if self.max_order_qty:
            return self.max_order_qty
        if self.freeze_qty:
            return self.freeze_qty - 1
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expiry"] = self.expiry.isoformat()
        d["extra"] = dict(self.extra)
        d["order_qty_cap"] = self.order_qty_cap
        return d


class InstrumentMaster:
    def __init__(self, instruments: Iterable[Instrument], source: str, as_of: dt.date):
        self.items = list(instruments)
        self.source = source
        self.as_of = as_of
        self._by_symbol = {i.tradingsymbol.upper(): i for i in self.items}

    def __len__(self) -> int:
        return len(self.items)

    def for_underlying(self, underlying: str) -> list[Instrument]:
        u = resources.index_rule(underlying)["kite_name"] if _is_index(underlying) else underlying.upper()
        return [i for i in self.items if i.underlying == u]

    def expiries(self, underlying: str, kind: str = "options") -> list[dt.date]:
        types = {"options": ("CE", "PE"), "futures": ("FUT",)}[kind]
        return sorted({i.expiry for i in self.for_underlying(underlying) if i.instrument_type in types})

    def lot_size(self, underlying: str, expiry: dt.date | None = None) -> int:
        rows = self.for_underlying(underlying)
        if expiry:
            rows = [r for r in rows if r.expiry == expiry]
        if not rows:
            raise InstrumentNotFound(f"No contracts for {underlying} {expiry or ''} in master ({self.source}).")
        lots = {r.lot_size for r in rows}
        if len(lots) > 1 and expiry is None:
            # Lot-size transitions: different series can carry different lots.
            nearest = min(rows, key=lambda r: r.expiry)
            return nearest.lot_size
        return lots.pop()

    def option(self, underlying: str, expiry: dt.date, strike: float, opt: str) -> Instrument:
        for i in self.for_underlying(underlying):
            if i.expiry == expiry and i.instrument_type == opt and abs(i.strike - strike) < 1e-6:
                return i
        strikes = sorted({i.strike for i in self.for_underlying(underlying) if i.expiry == expiry})
        near = sorted(strikes, key=lambda s: abs(s - strike))[:5]
        raise InstrumentNotFound(
            f"{underlying} {expiry} {strike:g} {opt} not listed. Nearest listed strikes: {sorted(near)}")

    def by_symbol(self, tradingsymbol: str) -> Instrument:
        try:
            return self._by_symbol[tradingsymbol.upper()]
        except KeyError:
            raise InstrumentNotFound(f"Trading symbol {tradingsymbol} not in master ({self.source}).") from None

    def resolve(self, text: str, today: dt.date | None = None) -> Instrument:
        return resolve(self, text, today or self.as_of)


def _is_index(name: str) -> bool:
    try:
        resources.index_rule(name)
        return True
    except KeyError:
        return False


_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _parse_date_tokens(tokens: list[str]) -> tuple[dict, list[str]]:
    """Extract an expiry hint from tokens; returns (hint, remaining_tokens)."""
    hint: dict = {}
    rest: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            hint["date"] = dt.date.fromisoformat(t)
        elif m := re.fullmatch(r"(\d{1,2})-?([A-Z]{3})-?(\d{2,4})?", t):
            if m.group(2) in _MONTHS:
                hint.update(day=int(m.group(1)), month=_MONTHS[m.group(2)])
                if m.group(3):
                    y = int(m.group(3))
                    hint["year"] = y + 2000 if y < 100 else y
            else:
                rest.append(t)
        elif re.fullmatch(r"\d{1,2}", t) and i + 1 < len(tokens) and tokens[i + 1][:3] in _MONTHS:
            hint.update(day=int(t), month=_MONTHS[tokens[i + 1][:3]])
            i += 1
            if i + 1 < len(tokens) and re.fullmatch(r"20\d{2}", tokens[i + 1]):
                hint["year"] = int(tokens[i + 1])
                i += 1
        elif t[:3] in _MONTHS and len(t) <= 9 and not hint:
            hint["month"] = _MONTHS[t[:3]]
            hint["monthly"] = True
        elif t in {"NEXT", "CURRENT", "NEAR", "WEEKLY"}:
            hint["nth"] = 0
        elif t in {"MONTHLY", "MONTH"}:
            hint["monthly"] = True
        elif t in {"FAR", "NEXT2"}:
            hint["nth"] = 1
        else:
            rest.append(t)
        i += 1
    return hint, rest


def resolve(master: InstrumentMaster, text: str, today: dt.date) -> Instrument:
    """Resolve e.g. 'NIFTY 23 Nov 24500 CE', 'banknifty monthly 52000 pe', 'NIFTY FUT', or a tradingsymbol."""
    raw = text.strip().upper()
    if raw in master._by_symbol:
        return master._by_symbol[raw]
    tokens = re.split(r"[\s,/]+", raw.replace("CALL", "CE").replace("PUT", "PE"))
    if not tokens or not _is_index(tokens[0]):
        raise InstrumentNotFound(f"Could not find an index name at the start of {text!r}.")
    underlying = resources.index_rule(tokens[0])["kite_name"]
    hint, rest = _parse_date_tokens(tokens[1:])
    opt = next((t for t in rest if t in {"CE", "PE", "FUT"}), None)
    strike_tok = next((t for t in rest if re.fullmatch(r"\d+(\.\d+)?", t)), None)
    # Allow '24500CE'
    for t in rest:
        if m := re.fullmatch(r"(\d+(?:\.\d+)?)(CE|PE)", t):
            strike_tok, opt = m.group(1), m.group(2)
    if opt is None:
        raise InstrumentNotFound(f"Specify CE, PE or FUT in {text!r}.")
    kind = "futures" if opt == "FUT" else "options"
    exps = [e for e in master.expiries(underlying, kind) if e >= today]
    if not exps:
        raise InstrumentNotFound(f"No live {kind} expiries for {underlying} in master.")
    expiry = _pick_expiry(exps, hint, underlying, text)
    if opt == "FUT":
        for i in master.for_underlying(underlying):
            if i.instrument_type == "FUT" and i.expiry == expiry:
                return i
        raise InstrumentNotFound(f"No {underlying} future for {expiry}.")
    if strike_tok is None:
        raise InstrumentNotFound(f"No strike found in {text!r}.")
    return master.option(underlying, expiry, float(strike_tok), opt)


def _pick_expiry(exps: list[dt.date], hint: dict, underlying: str, text: str) -> dt.date:
    if "date" in hint:
        if hint["date"] in exps:
            return hint["date"]
        raise InstrumentNotFound(f"{hint['date']} is not a listed {underlying} expiry. Listed: "
                                 f"{[e.isoformat() for e in exps[:6]]}")
    if "day" in hint:
        matches = [e for e in exps if e.day == hint["day"] and e.month == hint["month"]
                   and ("year" not in hint or e.year == hint["year"])]
        if matches:
            return matches[0]
        same_month = [e.isoformat() for e in exps if e.month == hint["month"]][:6]
        raise InstrumentNotFound(
            f"No {underlying} expiry on {hint['day']:02d}-{hint['month']:02d} ({text!r}). "
            f"Expiries that month: {same_month or [e.isoformat() for e in exps[:6]]}. "
            "Expiries move to the previous trading day when they fall on a holiday.")
    if hint.get("monthly"):
        by_month: dict[tuple[int, int], dt.date] = {}
        for e in exps:
            by_month[(e.year, e.month)] = max(by_month.get((e.year, e.month), e), e)
        monthly = sorted(by_month.values())
        if "month" in hint:
            monthly = [e for e in monthly if e.month == hint["month"]] or monthly
        return monthly[0]
    return exps[min(hint.get("nth", 0), len(exps) - 1)]

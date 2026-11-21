"""Common broker interface.

Every broker adapter exposes the same five capabilities, so skills never care which
broker the user has:

    load_master()            -> InstrumentMaster       (public file, no login, where offered)
    option_chain(idx, exp)   -> OptionChain            (login)
    basket_margin(legs)      -> dict                   (login)
    order_payload(intent)    -> dict                   (pure; used by the dry run)
    place_order(payload)     -> dict                   (login; only after confirmation)

`VERIFICATION` records where each piece came from, and is surfaced in outputs:
  "live"  - exercised against the real public endpoint while building this pack
  "sdk"   - path/fields read from the broker's official SDK source
  "docs"  - path/fields read from the broker's official API documentation
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any

import requests

from .. import http
from ..chain import OptionChain
from ..config import secret
from ..errors import AdapterError, ConfigError
from ..instruments import Instrument, InstrumentMaster
from ..session import IST, now_ist


@dataclass(frozen=True)
class OrderIntent:
    """Broker-neutral order. Quantity is in UNITS (lots x lot size)."""
    instrument: Instrument
    side: str            # BUY | SELL
    quantity: int
    order_type: str      # LIMIT | MARKET
    price: float | None
    product: str = "NRML"  # NRML (carry forward) | MIS (intraday)
    tag: str | None = None


class NotSupported(AdapterError):
    pass


class Broker:
    name = "base"
    display = "Base"
    exchanges = ("NFO", "BFO")
    env: tuple[str, ...] = ()          # credentials this broker needs (env vars)
    VERIFICATION: dict[str, str] = {}
    timeout = 20

    # ---------------- master ----------------
    def master_sources(self) -> list[tuple[str, str]]:
        """[(exchange, url)] of public master files. Empty when the master needs a login."""
        return []

    def parse_master(self, blob: bytes | str, exchange: str) -> list[Instrument]:
        raise NotSupported(f"{self.display}: no public instrument master parser")

    def load_master(self, ttl: float = 6 * 3600) -> InstrumentMaster:
        srcs = self.master_sources()
        if not srcs:
            raise NotSupported(f"{self.display}'s instrument master needs a login; use another master "
                               "(e.g. --master kite_public) for lot sizes and expiries.")
        items: list[Instrument] = []
        for ex, url in srcs:
            items.extend(self.parse_master(http.get(url, ttl=ttl, timeout=120, binary=True), ex))
        if not items:
            raise AdapterError(f"{self.display} master parsed to zero derivatives - format changed?")
        return InstrumentMaster(items, source=self.name, as_of=now_ist().date())

    # ---------------- authenticated ----------------
    def option_chain(self, index: str, expiry: dt.date, master: InstrumentMaster) -> OptionChain:
        raise NotSupported(f"{self.display}: option chain not implemented")

    def basket_margin(self, legs: list[dict], master: InstrumentMaster | None = None) -> dict:
        raise NotSupported(f"{self.display}: margin API not implemented")

    def order_payload(self, intent: OrderIntent) -> dict:
        raise NotSupported(f"{self.display}: order placement not implemented")

    def place_order(self, payload: dict) -> dict:
        raise NotSupported(f"{self.display}: order placement not implemented")

    # ---------------- helpers ----------------
    def creds(self) -> dict[str, str]:
        missing = [k for k in self.env if not os.environ.get(k)]
        if missing:
            raise ConfigError(f"{self.display} needs environment variables: {', '.join(missing)} "
                              "(never put credentials in files or chat).")
        return {k: secret(k) for k in self.env}

    def _request(self, method: str, url: str, *, headers: dict | None = None, json_body: Any = None,
                 data: Any = None, params: dict | None = None) -> Any:
        try:
            r = http.session().request(method, url, headers=headers, json=json_body, data=data, params=params,
                                       timeout=self.timeout)
        except requests.RequestException as e:
            raise AdapterError(f"{self.display} {method} {url}: {e}") from e
        try:
            body = r.json()
        except ValueError:
            raise AdapterError(f"{self.display} returned non-JSON (HTTP {r.status_code}) from {url}") from None
        if r.status_code >= 400:
            raise AdapterError(f"{self.display} HTTP {r.status_code}: {str(body)[:300]}")
        return body

    def capabilities(self) -> dict:
        return {
            "broker": self.name, "display": self.display,
            "public_master": bool(self.master_sources()),
            "option_chain": type(self).option_chain is not Broker.option_chain,
            "margin": type(self).basket_margin is not Broker.basket_margin,
            "orders": type(self).place_order is not Broker.place_order,
            "credentials": list(self.env),
            "verification": self.VERIFICATION,
        }


# ---------------- shared parsing helpers ----------------

def f(x, default=None):
    try:
        if x in (None, "", "-", "None"):
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def i(x, default=None):
    v = f(x)
    return default if v is None else int(round(v))


def first(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def ist_date_from_epoch(secs: float) -> dt.date:
    return dt.datetime.fromtimestamp(secs, tz=IST).date()


def detect_oi_unit(rows: list[dict], lot: int) -> str:
    """Brokers report OI either in contracts or in units. Exchange OI in units is always a
    multiple of the lot size; OI in contracts almost never is across a whole chain."""
    vals = [v for r in rows for k in ("ce_oi", "pe_oi") if (v := r.get(k)) not in (None, 0)]
    if lot <= 1 or len(vals) < 6:
        return "unknown"
    share = sum(1 for v in vals if float(v) % lot == 0) / len(vals)
    return "units" if share >= 0.95 else "contracts"


def finalise_chain(index: str, expiry: dt.date, spot: float, rows_by_strike: dict[float, dict], lot: int,
                   source: str, futures_price: float | None = None, stale_after_s: float = 60,
                   fetched_at: dt.datetime | None = None, oi_unit: str = "auto") -> OptionChain:
    rows = [rows_by_strike[k] for k in sorted(rows_by_strike)]
    for r in rows:
        for side in ("ce", "pe"):
            for fld in ("ltp", "bid", "ask", "oi", "doi", "volume", "iv_src"):
                r.setdefault(f"{side}_{fld}", None)
    unit = detect_oi_unit(rows, lot) if oi_unit == "auto" else oi_unit
    if unit == "units":
        for r in rows:
            for k in ("ce_oi", "pe_oi", "ce_doi", "pe_doi"):
                if r.get(k) is not None:
                    r[k] = r[k] / lot
    return OptionChain(underlying=index, expiry=expiry, spot=float(spot), fetched_at=fetched_at or now_ist(),
                       source=source, lot_size=lot, rows=rows, futures_price=futures_price,
                       stale_after_s=stale_after_s,
                       meta={"oi_unit": "contracts", "oi_unit_reported": unit})


def options_for(master: InstrumentMaster, index: str, expiry: dt.date) -> list[Instrument]:
    opts = [x for x in master.for_underlying(index) if x.expiry == expiry and x.instrument_type in ("CE", "PE")]
    if not opts:
        raise AdapterError(f"No {index} options for {expiry} in the {master.source} master.")
    return opts


def require_master(master: InstrumentMaster | None, broker: Broker) -> InstrumentMaster:
    if master is None:
        return broker.load_master()
    return master

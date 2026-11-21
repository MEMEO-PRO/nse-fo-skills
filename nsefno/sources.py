"""Choose a data source for the instrument master and the option chain."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from . import resources
from .chain import OptionChain
from .errors import AdapterError
from .instruments import InstrumentMaster


def get_master(source: str | None = None, files: list[str] | None = None) -> InstrumentMaster:
    source = source or os.environ.get("NSEFNO_MASTER", "kite_public")
    if source == "kite_public":
        from .adapters import kite

        return kite.load_instruments()
    if source == "kotak_neo":
        from .adapters import kotak_neo

        if not files:
            raise AdapterError("kotak_neo master needs --master-file nse_fo.csv [bse_fo.csv] "
                               "(download URLs come from client.scrip_master()).")
        return kotak_neo.load_instruments_from_csv(files)
    if source == "file":
        from .adapters import kite

        items = []
        for f in files or []:
            ex = "BFO" if "BFO" in Path(f).name.upper() else "NFO"
            items += kite.parse_instruments_csv(Path(f).read_text(encoding="utf-8"), ex)
        return InstrumentMaster(items, source="file", as_of=dt.date.today())
    raise AdapterError(f"Unknown master source {source!r}")


def resolve_expiry(master: InstrumentMaster | None, index: str, expiry: str, today: dt.date) -> dt.date:
    if expiry not in ("next", "monthly", "far"):
        return dt.date.fromisoformat(expiry)
    if master is not None:
        exps = [e for e in master.expiries(index) if e >= today]
    else:
        from .calendar import projected_expiries

        exps = [dt.date.fromisoformat(e["expiry"]) for e in projected_expiries(index, today, 8)]
    if not exps:
        raise AdapterError(f"No expiries for {index}")
    if expiry == "next":
        return exps[0]
    if expiry == "far":
        return exps[min(1, len(exps) - 1)]
    by_month: dict = {}
    for e in exps:
        by_month[(e.year, e.month)] = max(by_month.get((e.year, e.month), e), e)
    return sorted(by_month.values())[0]


def get_chain(index: str, expiry: dt.date, source: str = "nse_public", file: str | None = None,
              lot_size: int | None = None) -> OptionChain:
    if file:
        p = Path(file)
        payload = json.loads(p.read_text(encoding="utf-8"))
        if "rows" in payload:  # already normalised (saved snapshot / fixture)
            return OptionChain.from_dict(payload)
        from .adapters import nse_public

        return nse_public.parse(payload, resources.index_rule(index)["index"], expiry, lot_size)
    if source == "nse_public":
        rule = resources.index_rule(index)
        if not rule.get("nse_symbol"):
            raise AdapterError(f"{index} is a BSE index; the NSE public chain does not cover it. Use a broker adapter.")
        from .adapters import nse_public

        return nse_public.fetch_chain(rule["nse_symbol"], expiry, lot_size)
    if source == "kite":
        return kite_chain(index, expiry, get_master("kite_public"))
    raise AdapterError(f"Unknown chain source {source!r} (nse_public | kite | --file).")


def kite_chain(index: str, expiry: dt.date, master: InstrumentMaster) -> OptionChain:
    """Build a chain from Kite quotes (needs KITE_API_KEY/KITE_ACCESS_TOKEN). Kite reports OI in units;
    we convert to contracts with the master lot size."""
    from .adapters import kite
    from .session import now_ist

    rule = resources.index_rule(index)
    seg = rule["segment"]
    opts = [i for i in master.for_underlying(index) if i.expiry == expiry and i.instrument_type in ("CE", "PE")]
    if not opts:
        raise AdapterError(f"No {index} options for {expiry} in master.")
    spot_key = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE",
                "MIDCPNIFTY": "NSE:NIFTY MID SELECT", "NIFTYNXT50": "NSE:NIFTY NEXT 50",
                "SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX"}[rule["index"]]
    q = kite.quotes([f"{seg}:{i.tradingsymbol}" for i in opts] + [spot_key])
    lot = opts[0].lot_size
    rows: dict[float, dict] = {}
    for i in opts:
        d = q.get(f"{seg}:{i.tradingsymbol}")
        if not d:
            continue
        side = i.instrument_type.lower()
        depth = d.get("depth") or {}
        bid = (depth.get("buy") or [{}])[0].get("price") or None
        ask = (depth.get("sell") or [{}])[0].get("price") or None
        row = rows.setdefault(i.strike, {"strike": i.strike})
        row.update({f"{side}_ltp": d.get("last_price"), f"{side}_bid": bid, f"{side}_ask": ask,
                    f"{side}_oi": (d.get("oi") or 0) / lot,
                    f"{side}_doi": None, f"{side}_volume": d.get("volume"), f"{side}_iv_src": None})
    return OptionChain(underlying=rule["index"], expiry=expiry, spot=float(q[spot_key]["last_price"]),
                       fetched_at=now_ist(), source="kite", lot_size=lot,
                       rows=[rows[k] for k in sorted(rows)], stale_after_s=60, meta={"oi_unit": "contracts"})

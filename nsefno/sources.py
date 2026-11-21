"""Choose a data source for the instrument master and the option chain.

Masters:  kite_public (default) | upstox | dhan | fyers | angel | groww | shoonya | breeze |
          fivepaisa | aliceblue  (all public, no login)  | kotak_neo (CSV) | file (Kite-format CSV)
Chains:   nse_public (no login, best effort) | gdfl (vendor) | any broker name (login)
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from . import resources
from .chain import OptionChain
from .errors import AdapterError
from .instruments import InstrumentMaster

_MASTER_CACHE: dict[str, InstrumentMaster] = {}


def get_master(source: str | None = None, files: list[str] | None = None) -> InstrumentMaster:
    source = (source or os.environ.get("NSEFNO_MASTER", "kite_public")).lower()
    if source == "kotak_neo":
        from .adapters import kotak_neo

        if not files:
            raise AdapterError("kotak_neo master needs --master-file nse_fo.csv [bse_fo.csv] "
                               "(download URLs come from client.scrip_master()).")
        return kotak_neo.load_instruments_from_csv(files)
    if source == "file":
        from .brokers.kite import Kite

        items = []
        for f in files or []:
            ex = "BFO" if "BFO" in Path(f).name.upper() else "NFO"
            items += Kite().parse_master(Path(f).read_text(encoding="utf-8"), ex)
        return InstrumentMaster(items, source="file", as_of=dt.date.today())
    if source in _MASTER_CACHE:
        return _MASTER_CACHE[source]
    from .brokers import get_broker

    m = get_broker(source).load_master()
    if source == "kite_public":
        m.source = "kite_public"
    _MASTER_CACHE[source] = m
    return m


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


def broker_master(broker_name: str) -> InstrumentMaster:
    """The broker's own master when it publishes one (its trading symbols/tokens), else kite_public."""
    from .brokers import get_broker

    b = get_broker(broker_name)
    return get_master(b.name if b.master_sources() else "kite_public")


def get_chain(index: str, expiry: dt.date, source: str = "nse_public", file: str | None = None,
              lot_size: int | None = None) -> OptionChain:
    if file:
        payload = json.loads(Path(file).read_text(encoding="utf-8"))
        if "rows" in payload:  # already normalised (saved snapshot / fixture)
            return OptionChain.from_dict(payload)
        from .adapters import nse_public

        return nse_public.parse(payload, resources.index_rule(index)["index"], expiry, lot_size)
    if source == "nse_public":
        rule = resources.index_rule(index)
        if not rule.get("nse_symbol"):
            raise AdapterError(f"{index} is a BSE index; the NSE public chain does not cover it. "
                               "Use --source <broker> (e.g. kite, upstox, dhan, fyers).")
        from .adapters import nse_public

        return nse_public.fetch_chain(rule["nse_symbol"], expiry, lot_size)
    if source == "gdfl":
        from .vendors import gdfl

        lot = lot_size or get_master().lot_size(index, expiry)
        return gdfl.option_chain(index, expiry, lot)
    from .brokers import get_broker

    return get_broker(source).option_chain(index, expiry, broker_master(source))

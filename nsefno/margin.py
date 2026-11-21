"""Broker margin check (SPAN + exposure, with hedge benefit where the broker API reports it)."""

from __future__ import annotations

from .brokers import get_broker
from .instruments import InstrumentMaster


def resolve_legs(legs: list[dict], master: InstrumentMaster) -> list[dict]:
    """Accept legs as {"instrument": "NIFTY 23 Nov 26200 CE", "side", "lots"|"qty", "price"} or with an
    explicit tradingsymbol; returns legs enriched with broker symbol, token, exchange and qty in units."""
    out = []
    for leg in legs:
        inst = master.resolve(leg.get("instrument") or leg["tradingsymbol"])
        qty = int(leg.get("qty") or int(leg.get("lots", 1)) * inst.lot_size)
        out.append({**leg, "tradingsymbol": inst.tradingsymbol, "token": inst.token, "exchange": inst.exchange,
                    "qty": qty, "instrument_obj": inst})
    return out


def basket_margin(broker: str, legs: list[dict], master: InstrumentMaster | None = None) -> dict:
    from .sources import broker_master

    b = get_broker(broker)
    master = master or broker_master(b.name)
    resolved = resolve_legs(legs, master)
    res = b.basket_margin(resolved, master)
    res["legs"] = [{k: v for k, v in leg.items() if k != "instrument_obj"} for leg in resolved]
    res["verification"] = b.VERIFICATION.get("margin")
    return res

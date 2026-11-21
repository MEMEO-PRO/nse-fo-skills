"""Round-trip cost of Indian F&O trades: brokerage, STT, exchange txn, SEBI fee, stamp, GST.

Rates come from data/charges.yaml, selected by trade date (`effective_from`).
A leg = {"instrument": "CE"|"PE"|"FUT", "side": "BUY"|"SELL", "price": premium or futures price,
         "qty": units (lots * lot_size), "exchange": "NSE"|"BSE", "orders": executed orders (default 1)}
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import resources
from .session import now_ist


def _pick(entries: list[dict], on: dt.date) -> dict:
    valid = [e for e in entries if _d(e["effective_from"]) <= on]
    if not valid:
        raise ValueError(f"No rate effective on {on}")
    return max(valid, key=lambda e: _d(e["effective_from"]))


def _d(x) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x))


@dataclass
class Leg:
    instrument: str
    side: str
    price: float
    qty: int
    exchange: str = "NSE"
    orders: int = 1
    strike: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Leg:
        return cls(instrument=d["instrument"].upper(), side=d["side"].upper(), price=float(d["price"]),
                   qty=int(d["qty"]), exchange=d.get("exchange", "NSE").upper(), orders=int(d.get("orders", 1)),
                   strike=d.get("strike"))


def rates_on(on: dt.date) -> dict:
    c = resources.charges()
    return {
        "stt": _pick(c["stt"], on),
        "txn": {ex: _pick(v, on) for ex, v in c["exchange_txn"].items()},
        "sebi": _pick(c["sebi_fee"], on),
        "stamp": _pick(c["stamp_duty"], on),
        "gst": _pick(c["gst"], on),
    }


def _brokerage(leg: Leg, broker: str, turnover: float) -> float:
    plan = resources.charges()["brokerage"][broker]["option" if leg.instrument in ("CE", "PE") else "future"]
    if plan["type"] == "flat_per_order":
        return plan["amount"] * leg.orders
    if plan["type"] == "min_of_pct_or_flat":
        per_order_turnover = turnover / max(leg.orders, 1)
        return min(per_order_turnover * plan["pct"] / 100, plan["amount"]) * leg.orders
    raise ValueError(f"unknown brokerage type {plan['type']}")


def leg_cost(leg: Leg, broker: str = "zerodha", on: dt.date | None = None) -> dict:
    on = on or now_ist().date()
    R = rates_on(on)
    is_opt = leg.instrument in ("CE", "PE")
    turnover = leg.price * leg.qty
    brokerage = _brokerage(leg, broker, turnover)
    if is_opt:
        stt = turnover * R["stt"]["option_sell_premium_pct"] / 100 if leg.side == "SELL" else 0.0
        txn = turnover * R["txn"][leg.exchange]["option_premium_pct"] / 100
        stamp = turnover * R["stamp"]["option_buy_pct"] / 100 if leg.side == "BUY" else 0.0
    else:
        stt = turnover * R["stt"]["future_sell_pct"] / 100 if leg.side == "SELL" else 0.0
        txn = turnover * R["txn"][leg.exchange]["future_pct"] / 100
        stamp = turnover * R["stamp"]["future_buy_pct"] / 100 if leg.side == "BUY" else 0.0
    sebi = turnover * R["sebi"]["per_crore"] / 1e7
    gst = (brokerage + txn + sebi) * R["gst"]["pct"] / 100
    total = brokerage + stt + txn + sebi + stamp + gst
    return {"instrument": leg.instrument, "side": leg.side, "price": leg.price, "qty": leg.qty,
            "exchange": leg.exchange, "turnover": round(turnover, 2),
            "brokerage": round(brokerage, 2), "stt": round(stt, 2), "exchange_txn": round(txn, 2),
            "sebi_fee": round(sebi, 2), "stamp_duty": round(stamp, 2), "gst": round(gst, 2),
            "total": round(total, 2)}


def exercise_stt(intrinsic_per_unit: float, qty: int, on: dt.date | None = None) -> float:
    """STT charged to the BUYER when a long ITM option is exercised at expiry (on intrinsic value)."""
    R = rates_on(on or now_ist().date())
    return round(intrinsic_per_unit * qty * R["stt"]["option_exercise_intrinsic_pct"] / 100, 2)


def trade_cost(legs: list[dict | Leg], broker: str = "zerodha", on: dt.date | None = None,
               round_trip: bool = True, exit_prices: list[float] | None = None) -> dict:
    """Cost of entering legs and (if round_trip) exiting them at `exit_prices` (default: entry prices)."""
    on = on or now_ist().date()
    legs = [x if isinstance(x, Leg) else Leg.from_dict(x) for x in legs]
    lines = [leg_cost(leg, broker, on) | {"phase": "entry"} for leg in legs]
    if round_trip:
        exits = exit_prices or [leg.price for leg in legs]
        for leg, px in zip(legs, exits, strict=True):
            ex = Leg(leg.instrument, "SELL" if leg.side == "BUY" else "BUY", px, leg.qty, leg.exchange, leg.orders)
            lines.append(leg_cost(ex, broker, on) | {"phase": "exit"})
    keys = ("brokerage", "stt", "exchange_txn", "sebi_fee", "stamp_duty", "gst", "total")
    totals = {k: round(sum(line[k] for line in lines), 2) for k in keys}
    # Breakeven in premium points: cost spread over the position's unit count (max qty across legs).
    units = max(leg.qty for leg in legs)
    R = rates_on(on)
    return {
        "broker": broker, "trade_date": on.isoformat(), "round_trip": round_trip,
        "lines": lines, "totals": totals,
        "breakeven_points": round(totals["total"] / units, 3) if units else None,
        "units": units,
        "rates_used": {
            "stt_option_sell_pct": R["stt"]["option_sell_premium_pct"],
            "stt_future_sell_pct": R["stt"]["future_sell_pct"],
            "stt_effective_from": str(R["stt"]["effective_from"]),
            "nse_option_txn_pct": R["txn"]["NSE"]["option_premium_pct"],
            "bse_option_txn_pct": R["txn"]["BSE"]["option_premium_pct"],
            "sebi_per_crore": R["sebi"]["per_crore"], "stamp_option_buy_pct": R["stamp"]["option_buy_pct"],
            "gst_pct": R["gst"]["pct"],
        },
        "notes": ["Exercise of long ITM options at expiry attracts STT on intrinsic value "
                  f"({R['stt']['option_exercise_intrinsic_pct']}%), paid by the buyer - not included above; "
                  "use exercise_stt() / --exercise.",
                  "Excludes DP charges, call-and-trade fees and auto square-off fees."],
    }

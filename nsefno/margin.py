"""Broker margin check (SPAN + exposure, with hedge benefit) for a basket."""

from __future__ import annotations

from .errors import ConfigError


def kite_basket(legs: list[dict]) -> dict:
    """legs: {"tradingsymbol", "exchange": NFO|BFO, "side": BUY|SELL, "qty", "price"(optional), "product": NRML|MIS}"""
    from .adapters import kite

    orders = [{"exchange": leg["exchange"], "tradingsymbol": leg["tradingsymbol"],
               "transaction_type": leg["side"].upper(), "variety": "regular",
               "product": leg.get("product", "NRML"),
               "order_type": "LIMIT" if leg.get("price") else "MARKET",
               "quantity": int(leg["qty"]), "price": float(leg.get("price") or 0), "trigger_price": 0}
              for leg in legs]
    data = kite.basket_margin(orders)
    initial, final = data.get("initial", {}), data.get("final", {})
    return {
        "broker": "kite",
        "initial_total": initial.get("total"),
        "final_total": final.get("total"),
        "span": final.get("span"), "exposure": final.get("exposure"),
        "option_premium": final.get("option_premium"),
        "hedge_benefit": None if initial.get("total") is None or final.get("total") is None
        else round(initial["total"] - final["total"], 2),
        "per_order": data.get("orders"),
    }


def neo_basket(legs: list[dict]) -> dict:
    """Kotak Neo margin via the official SDK (margin_required per order, summed - Neo's
    basket endpoint support varies by SDK version; hedge benefit is NOT captured here)."""
    from .adapters import kotak_neo

    c = kotak_neo.client()
    per = []
    for leg in legs:
        r = c.margin_required(exchange_segment="nse_fo" if leg["exchange"] == "NFO" else "bse_fo",
                              price=str(leg.get("price") or 0), order_type="L" if leg.get("price") else "MKT",
                              product=leg.get("product", "NRML"), quantity=str(int(leg["qty"])),
                              instrument_token=str(leg["token"]),
                              transaction_type="B" if leg["side"].upper() == "BUY" else "S")
        per.append(r)
    return {"broker": "kotak_neo", "per_order": per,
            "note": "Sum of per-order margins; hedge benefit not reflected. Verify in the Neo app."}


def basket_margin(broker: str, legs: list[dict]) -> dict:
    if broker == "kite":
        return kite_basket(legs)
    if broker == "kotak_neo":
        return neo_basket(legs)
    raise ConfigError(f"Unsupported broker {broker!r} (kite | kotak_neo).")

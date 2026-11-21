"""Global Datafeeds (GFDL) REST - option chain via GetLastQuoteOptionChain.

Docs give the function names, parameters and response fields, but the host is per-subscription
(placeholder 'http://endpoint:port' in the docs) - set GDFL_ENDPOINT and GDFL_ACCESS_KEY.
Instrument identifiers use the documented long format, e.g. OPTIDX_NIFTY_23NOV2026_CE_26000."""

from __future__ import annotations

import datetime as dt

from ..brokers.base import f, finalise_chain
from ..config import secret
from ..errors import AdapterError
from ..resources import index_rule

EXCHANGE = {"NSE": "NFO", "BSE": "BFO"}


def _ci(d: dict, key: str):
    """Case-insensitive lookup (docs show PascalCase field names; JSON samples show UPPERCASE)."""
    lk = key.lower()
    for k, v in d.items():
        if k.lower() == lk:
            return v
    return None


def parse_identifier(ident: str) -> tuple[str, float] | None:
    parts = ident.split("_")
    if len(parts) != 5 or parts[3] not in ("CE", "PE"):
        return None
    return parts[3].lower(), float(parts[4])


def option_chain(index: str, expiry: dt.date, lot_size: int, spot: float | None = None):
    from .. import http

    rule = index_rule(index)
    base = secret("GDFL_ENDPOINT").rstrip("/")
    params = {"accessKey": secret("GDFL_ACCESS_KEY"), "exchange": EXCHANGE[rule["exchange"]],
              "product": rule["index"], "expiry": expiry.strftime("%d%b%Y").upper()}
    r = http.session().get(f"{base}/GetLastQuoteOptionChain/", params=params, timeout=20)
    if r.status_code >= 400:
        raise AdapterError(f"GFDL HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    items = data if isinstance(data, list) else (_ci(data, "Result") or _ci(data, "Data") or [])
    rows = {}
    for d in items:
        parsed = parse_identifier(str(_ci(d, "InstrumentIdentifier") or ""))
        if not parsed:
            continue
        side, k = parsed
        oi, doi = f(_ci(d, "OpenInterest")), f(_ci(d, "OpenInterestChange"))
        rows.setdefault(k, {"strike": k}).update({
            f"{side}_ltp": f(_ci(d, "LastTradePrice")), f"{side}_bid": f(_ci(d, "BuyPrice")) or None,
            f"{side}_ask": f(_ci(d, "SellPrice")) or None, f"{side}_oi": oi, f"{side}_doi": doi,
            f"{side}_volume": f(_ci(d, "TotalQtyTraded"))})
    if not rows:
        raise AdapterError("GFDL option chain returned no option rows.")
    if spot is None:
        k0 = min(rows, key=lambda k: abs((rows[k].get("ce_ltp") or 1e9) - (rows[k].get("pe_ltp") or 0)))
        spot = k0 + (rows[k0].get("ce_ltp") or 0) - (rows[k0].get("pe_ltp") or 0)
    return finalise_chain(rule["index"], expiry, spot, rows, lot_size, "gdfl")

"""NSE public option-chain JSON (nseindia.com) - BEST EFFORT, not for live trading.

The endpoint is undocumented, needs a cookie from a prior page visit, is rate-limited
and changes without notice. We cache 60 s, back off on errors and fail loudly on
schema drift. OI in this feed is reported in CONTRACTS (lots).
"""

from __future__ import annotations

import datetime as dt

import requests

from .. import http
from ..chain import OptionChain
from ..errors import AdapterError
from ..session import IST, now_ist

HOME = "https://www.nseindia.com/option-chain"
V3 = "https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={sym}&expiry={exp}"
CONTRACT_INFO = "https://www.nseindia.com/api/option-chain-contract-info?symbol={sym}"
LEGACY = "https://www.nseindia.com/api/option-chain-indices?symbol={sym}"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": http.USER_AGENT, "Accept": "application/json",
                      "Referer": HOME, "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get(HOME, timeout=15)  # cookie warm-up
    except requests.RequestException as e:
        raise AdapterError(f"NSE warm-up failed: {e}") from e
    return s


def _num(x):
    try:
        return None if x in (None, "", "-") else float(x)
    except (TypeError, ValueError):
        return None


def _side(d: dict | None, prefix: str) -> dict:
    d = d or {}
    return {
        f"{prefix}_ltp": _num(d.get("lastPrice")),
        f"{prefix}_bid": _num(d.get("buyPrice1", d.get("bidprice"))),
        f"{prefix}_ask": _num(d.get("sellPrice1", d.get("askPrice"))),
        f"{prefix}_oi": _num(d.get("openInterest")),
        f"{prefix}_doi": _num(d.get("changeinOpenInterest")),
        f"{prefix}_volume": _num(d.get("totalTradedVolume")),
        f"{prefix}_iv_src": _num(d.get("impliedVolatility")),
    }


def parse(payload: dict, underlying: str, expiry: dt.date, lot_size: int | None,
          fetched_at: dt.datetime | None = None) -> OptionChain:
    rec = payload.get("records") or {}
    data = rec.get("data") or payload.get("filtered", {}).get("data")
    if not data:
        raise AdapterError("NSE chain payload has no records.data - schema changed or empty response.")
    exp_key = expiry.strftime("%d-%b-%Y")
    rows = []
    for item in data:
        e = item.get("expiryDates") or item.get("expiryDate")
        if e and e != exp_key:
            continue
        rows.append({"strike": float(item["strikePrice"]), **_side(item.get("CE"), "ce"), **_side(item.get("PE"), "pe")})
    if not rows:
        raise AdapterError(f"No strikes for expiry {exp_key} in NSE payload.")
    rows.sort(key=lambda r: r["strike"])
    spot = _num(rec.get("underlyingValue"))
    ts = rec.get("timestamp")
    if fetched_at is None:
        fetched_at = dt.datetime.strptime(ts, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST) if ts else now_ist()
    return OptionChain(underlying=underlying, expiry=expiry, spot=spot, fetched_at=fetched_at,
                       source="nse_public", lot_size=lot_size, rows=rows, stale_after_s=120,
                       meta={"exchange_timestamp": ts, "oi_unit": "contracts"})


def infer_expiry(payload: dict) -> dt.date:
    """Nearest expiry present in a saved NSE payload."""
    rec = payload.get("records") or {}
    cands = rec.get("expiryDates") or sorted({i.get("expiryDates") or i.get("expiryDate")
                                             for i in rec.get("data", [])} - {None})
    if not cands:
        raise AdapterError("Cannot infer expiry from NSE payload; pass --expiry YYYY-MM-DD.")
    return min(dt.datetime.strptime(c, "%d-%b-%Y").date() for c in cands)


def fetch_chain(underlying: str, expiry: dt.date, lot_size: int | None = None) -> OptionChain:
    s = _session()
    url = V3.format(sym=underlying, exp=expiry.strftime("%d-%b-%Y"))
    try:
        payload = http.get_json(url, sess=s, ttl=60)
    except AdapterError:
        payload = http.get_json(LEGACY.format(sym=underlying), sess=s, ttl=60)
    return parse(payload, underlying, expiry, lot_size)

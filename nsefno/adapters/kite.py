"""Zerodha Kite Connect adapter.

- `load_instruments()` uses the PUBLIC instruments dump (https://api.kite.trade/instruments/{EXCHANGE}),
  which needs no login - this is the default no-key instrument master.
- Quotes / margins / orders need a Kite Connect app: env KITE_API_KEY + KITE_ACCESS_TOKEN.
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from .. import http
from ..config import secret
from ..errors import AdapterError
from ..instruments import Instrument, InstrumentMaster
from ..session import now_ist

BASE = "https://api.kite.trade"
SEGMENTS = {"NFO": "NFO", "BFO": "BFO"}


def parse_instruments_csv(text: str, exchange: str) -> list[Instrument]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        itype = r.get("instrument_type", "")
        if itype not in ("CE", "PE", "FUT") or not r.get("expiry"):
            continue
        out.append(Instrument(
            exchange=exchange, underlying=r["name"].strip('"'), instrument_type=itype,
            expiry=dt.date.fromisoformat(r["expiry"]), strike=float(r["strike"] or 0),
            lot_size=int(float(r["lot_size"])), tick_size=float(r["tick_size"]),
            tradingsymbol=r["tradingsymbol"], token=r["instrument_token"], source="kite_public",
        ))
    if not out:
        raise AdapterError(f"Kite instruments dump for {exchange} parsed to zero derivatives - format changed?")
    return out


def load_instruments(exchanges=("NFO", "BFO"), ttl: float = 6 * 3600) -> InstrumentMaster:
    items: list[Instrument] = []
    for ex in exchanges:
        text = http.get(f"{BASE}/instruments/{SEGMENTS[ex]}", ttl=ttl, timeout=60)
        items.extend(parse_instruments_csv(text, ex))
    return InstrumentMaster(items, source="kite_public", as_of=now_ist().date())


# ---------------- authenticated endpoints ----------------

def _auth_headers() -> dict:
    key = secret("KITE_API_KEY")
    tok = secret("KITE_ACCESS_TOKEN")
    return {"X-Kite-Version": "3", "Authorization": f"token {key}:{tok}"}


def _check(resp) -> dict:
    try:
        body = resp.json()
    except ValueError as e:
        raise AdapterError(f"Kite returned non-JSON (HTTP {resp.status_code})") from e
    if resp.status_code >= 400 or body.get("status") != "success":
        raise AdapterError(f"Kite error {resp.status_code}: {body.get('error_type')} {body.get('message')}")
    return body["data"]


def quotes(instruments: list[str]) -> dict:
    """instruments like ['NFO:NIFTY26NOV24500CE']. Max 500 per call."""
    s = http.session()
    out: dict = {}
    for i in range(0, len(instruments), 500):
        params = [("i", x) for x in instruments[i:i + 500]]
        out.update(_check(s.get(f"{BASE}/quote", params=params, headers=_auth_headers(), timeout=20)))
    return out


def basket_margin(orders: list[dict], consider_positions: bool = True) -> dict:
    """POST /margins/basket - SPAN + exposure with hedge benefit for the basket."""
    s = http.session()
    r = s.post(f"{BASE}/margins/basket", params={"consider_positions": str(consider_positions).lower(),
                                                 "mode": "compact"},
               json=orders, headers=_auth_headers(), timeout=20)
    return _check(r)


def place_order(payload: dict, variety: str = "regular") -> dict:
    s = http.session()
    r = s.post(f"{BASE}/orders/{variety}", data=payload, headers=_auth_headers(), timeout=20)
    return _check(r)

"""NSE end-of-day archives: UDiFF F&O bhavcopy (official, stable, no login).

URL: https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
Used for IV history (ATM IV per day), lot sizes (NewBrdLotQty) and journal marks.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import zipfile

from .. import greeks as g
from .. import http
from ..errors import AdapterError
from ..session import IST

URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d}_F_0000.csv.zip"
INDEX_OPT, INDEX_FUT = "IDO", "IDF"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


def fetch_bhavcopy(day: dt.date, ttl: float = 30 * 86400) -> str:
    blob = http.get(URL.format(d=day.strftime("%Y%m%d")), ttl=ttl, binary=True, timeout=60)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = z.namelist()[0]
            return z.read(name).decode("utf-8")
    except zipfile.BadZipFile as e:
        raise AdapterError(f"Bhavcopy for {day} is not a zip (holiday or not yet published?)") from e


def parse_bhavcopy(text: str, underlying: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("TckrSymb") != underlying or r.get("FinInstrmTp") not in (INDEX_OPT, INDEX_FUT):
            continue
        rows.append({
            "date": r["TradDt"], "type": r["FinInstrmTp"], "expiry": r["XpryDt"],
            "strike": _f(r.get("StrkPric")), "opt": (r.get("OptnTp") or "").strip(),
            "close": _f(r.get("ClsPric")), "settle": _f(r.get("SttlmPric")),
            "underlying_px": _f(r.get("UndrlygPric")), "oi": _f(r.get("OpnIntrst")),
            "lot_size": int(_f(r.get("NewBrdLotQty"))) if r.get("NewBrdLotQty") else None,
        })
    return rows


def atm_iv_from_bhavcopy(rows: list[dict], min_days: int = 2, r: float = 0.055) -> dict | None:
    """ATM implied vol (mean of call & put) for the nearest expiry with >= min_days to go."""
    if not rows:
        return None
    day = dt.date.fromisoformat(rows[0]["date"])
    expiries = sorted({dt.date.fromisoformat(x["expiry"]) for x in rows if x["type"] == INDEX_OPT})
    expiries = [e for e in expiries if (e - day).days >= min_days]
    if not expiries:
        return None
    exp = expiries[0]
    opts = [x for x in rows if x["type"] == INDEX_OPT and x["expiry"] == exp.isoformat()]
    spot = next((x["underlying_px"] for x in opts if not math.isnan(x["underlying_px"])), math.nan)
    futs = sorted((x for x in rows if x["type"] == INDEX_FUT), key=lambda x: x["expiry"])
    t = g.year_fraction(dt.datetime.combine(day, dt.time(15, 30), tzinfo=IST), exp)
    strikes = sorted({x["strike"] for x in opts})
    if not strikes or math.isnan(spot):
        return None
    k = min(strikes, key=lambda s: abs(s - spot))
    c = next((x["close"] for x in opts if x["strike"] == k and x["opt"] == "CE"), math.nan)
    p = next((x["close"] for x in opts if x["strike"] == k and x["opt"] == "PE"), math.nan)
    fwd = k + (c - p) * math.exp(r * t) if not (math.isnan(c) or math.isnan(p)) else (
        futs[0]["settle"] if futs else spot)
    ivs = [g.implied_vol(px, fwd, k, t, r, is_call) for px, is_call in ((c, True), (p, False))]
    ivs = [v for v in ivs if not math.isnan(v)]
    if not ivs:
        return None
    return {"date": day.isoformat(), "expiry": exp.isoformat(), "atm_strike": k, "forward": round(fwd, 2),
            "atm_iv": round(100 * sum(ivs) / len(ivs), 3)}

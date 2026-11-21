"""Regenerate the SYNTHETIC option-chain fixtures in tests/fixtures/.

The repo ships no NSE market data (redistribution). These fixtures are generated from
Black-76 with a realistic put skew and OI profile, written in the exact NSE
option-chain JSON layout so the parser, analytics and golden tests run offline.
Deterministic: same output every run.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np

from nsefno import greeks as g
from nsefno.session import IST

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
R = 0.055


def _tick(x: float) -> float:
    return round(max(0.05, round(x / 0.05) * 0.05), 2)


def make(symbol, spot, expiry, ts, step, n_side, atm_iv, skew, curv, call_peak, put_peak, oi_scale, seed,
         put_heavy=1.0):
    rng = np.random.default_rng(seed)
    now = dt.datetime.strptime(ts, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    t = g.year_fraction(now, expiry)
    F = spot * math.exp(R * t) * 0.99995
    atm = round(spot / step) * step
    strikes = [atm + i * step for i in range(-n_side, n_side + 1)]
    data = []
    for k in strikes:
        m = math.log(k / F) / (atm_iv * math.sqrt(t))  # standard deviations from the forward
        iv = max(0.05, atm_iv + skew * m + curv * min(m * m, 9.0))
        rec = {"strikePrice": k, "expiryDates": expiry.strftime("%d-%b-%Y")}
        for side, is_call, peak in (("CE", True, call_peak), ("PE", False, put_peak)):
            px = float(g.price(F, k, t, iv, R, is_call))
            if px < 0.05:
                px = 0.05
            spread = max(0.05, round(px * 0.006 / 0.05) * 0.05)
            dist = (k - peak) / (step * 6)
            base = math.exp(-0.5 * dist * dist) + 0.15 * math.exp(-abs(k - atm) / (step * 10))
            if k % (step * 10) == 0:
                base *= 1.6  # round-number strikes carry more OI
            oi = int(oi_scale * base * (put_heavy if side == "PE" else 1.0) * (0.85 + 0.3 * rng.random()))
            rec[side] = {
                "strikePrice": k, "expiryDate": expiry.strftime("%d-%b-%Y"), "underlying": symbol,
                "openInterest": oi, "changeinOpenInterest": int(oi * (rng.random() - 0.35) * 0.4),
                "totalTradedVolume": int(oi * (2 + 6 * rng.random())), "impliedVolatility": round(iv * 100, 2),
                "lastPrice": _tick(px), "buyPrice1": _tick(px - spread / 2), "sellPrice1": _tick(px + spread / 2),
                "underlyingValue": spot,
            }
        data.append(rec)
    return {"records": {"timestamp": ts, "underlyingValue": spot,
                        "expiryDates": [expiry.strftime("%d-%b-%Y")], "data": data},
            "_synthetic": {"generator": "scripts/make_fixtures.py", "atm_iv": atm_iv, "rate": R}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {
        "nifty_2026-11-23.json": make("NIFTY", 26152.35, dt.date(2026, 11, 23), "20-Nov-2026 15:30:00", 50, 40,
                                      0.105, -0.016, 0.006, 26500, 25800, 140000, 1),
        "nifty_2026-12-01.json": make("NIFTY", 26152.35, dt.date(2026, 12, 1), "20-Nov-2026 15:30:00", 50, 40,
                                      0.118, -0.014, 0.005, 26600, 25700, 90000, 2),
        "nifty_2026-12-29.json": make("NIFTY", 26152.35, dt.date(2026, 12, 29), "20-Nov-2026 15:30:00", 100, 30,
                                      0.128, -0.013, 0.004, 27000, 25500, 60000, 3),
        "banknifty_2026-11-23.json": make("BANKNIFTY", 59240.80, dt.date(2026, 11, 23), "20-Nov-2026 15:30:00", 100,
                                          40, 0.12, -0.015, 0.005, 60000, 58500, 40000, 4),
        # Put-heavy book just above a big put strike -> negative net GEX near spot (classic convention).
        "nifty_negative_gamma.json": make("NIFTY", 25410.10, dt.date(2026, 11, 23), "20-Nov-2026 15:30:00", 50, 40,
                                          0.16, -0.02, 0.006, 26200, 25400, 140000, 5, put_heavy=2.6),
    }
    for name, payload in specs.items():
        (OUT / name).write_text(json.dumps(payload, indent=1))
        print("wrote", name)


if __name__ == "__main__":
    main()

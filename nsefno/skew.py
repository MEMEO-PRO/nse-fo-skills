"""IV smile, 25/10-delta risk reversal & butterfly, ATM term structure, IV percentile."""

from __future__ import annotations

import math

import numpy as np


def _arr(rows, key):
    return np.array([np.nan if r.get(key) is None else float(r[key]) for r in rows])


def otm_smile(analysed: dict) -> list[dict]:
    """OTM-wing smile: put IV below the forward, call IV at/above it."""
    F = analysed["summary"]["forward"]
    out = []
    for r in analysed["rows"]:
        k = r["strike"]
        side = "pe" if k < F else "ce"
        iv = r.get(f"{side}_iv")
        if iv is None:
            continue
        out.append({"strike": k, "moneyness": round(math.log(k / F), 5), "iv": round(iv, 3),
                    "side": side.upper(), "delta": None if r.get(f"{side}_delta") is None
                    else round(float(r[f"{side}_delta"]), 4)})
    return out


def iv_at_delta(analysed: dict, target: float, side: str) -> float | None:
    """Interpolate IV at a Black-76 delta (calls: +0.25, puts: -0.25) using OTM options only."""
    F = analysed["summary"]["forward"]
    rows = [r for r in analysed["rows"]
            if r.get(f"{side}_iv") is not None and r.get(f"{side}_delta") is not None
            and ((side == "ce" and r["strike"] >= F) or (side == "pe" and r["strike"] <= F))]
    if len(rows) < 2:
        return None
    d = _arr(rows, f"{side}_delta")
    iv = _arr(rows, f"{side}_iv")
    order = np.argsort(d)
    d, iv = d[order], iv[order]
    if not (d.min() <= target <= d.max()):
        return None
    return float(np.interp(target, d, iv))


def skew_metrics(analysed: dict) -> dict:
    s = analysed["summary"]
    atm = s["atm_iv"]
    out = {"expiry": s["expiry"], "days_to_expiry": s["days_to_expiry"], "forward": s["forward"], "atm_iv": atm}
    for dlt in (25, 10):
        c = iv_at_delta(analysed, dlt / 100, "ce")
        p = iv_at_delta(analysed, -dlt / 100, "pe")
        out[f"call_{dlt}d_iv"] = None if c is None else round(c, 3)
        out[f"put_{dlt}d_iv"] = None if p is None else round(p, 3)
        out[f"rr_{dlt}d"] = None if c is None or p is None else round(c - p, 3)
        out[f"bf_{dlt}d"] = None if c is None or p is None or atm is None else round((c + p) / 2 - atm, 3)
    rr = out.get("rr_25d")
    out["skew_read"] = (None if rr is None else
                        "put skew (downside protection bid)" if rr < -0.25 else
                        "call skew (upside bid)" if rr > 0.25 else "roughly flat")
    return out


def term_structure(per_expiry: list[dict]) -> dict:
    pts = sorted(({"expiry": m["expiry"], "days_to_expiry": m["days_to_expiry"], "atm_iv": m["atm_iv"]}
                  for m in per_expiry if m.get("atm_iv") is not None), key=lambda x: x["days_to_expiry"])
    shape = None
    if len(pts) >= 2:
        slope = pts[-1]["atm_iv"] - pts[0]["atm_iv"]
        shape = "contango (front cheaper)" if slope > 0.25 else "backwardation (front richer)" if slope < -0.25 \
            else "flat"
    return {"points": pts, "shape": shape}


def iv_percentile(current: float, history: list[float]) -> dict:
    """IV percentile = % of past observations below current; IV rank = position in [min, max]."""
    h = [x for x in history if x is not None and not math.isnan(x)]
    if len(h) < 20:
        return {"iv_percentile": None, "iv_rank": None, "n_obs": len(h),
                "note": "need >= 20 daily observations (run `nsefno ivhistory` to backfill from bhavcopy)"}
    arr = np.array(h)
    pct = float((arr < current).mean() * 100)
    lo, hi = float(arr.min()), float(arr.max())
    rank = None if hi == lo else (current - lo) / (hi - lo) * 100
    return {"iv_percentile": round(pct, 1), "iv_rank": None if rank is None else round(rank, 1),
            "n_obs": len(h), "min": round(lo, 2), "max": round(hi, 2), "median": round(float(np.median(arr)), 2)}

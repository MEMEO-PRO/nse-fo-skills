"""Gamma exposure (GEX) by strike, zero-gamma flip and call/put walls.

GEX_k (INR per 1% move) = gamma_k * OI_k(contracts) * lot_size * S^2 * 0.01

Sign convention is an ASSUMPTION about who holds the other side - it is always
reported in the output:
  * "classic" (default; SqueezeMetrics/SpotGamma style): dealers are long call OI and
    short put OI -> call GEX positive, put GEX negative.
  * "dealer_short": dealers are net short ALL customer options -> every strike negative.
    Arguably closer to Indian index options, where non-dealer writers dominate;
    useful as a sensitivity check.
Positive net GEX => hedging flows dampen moves; negative => hedging amplifies moves.
"""

from __future__ import annotations

import math

import numpy as np

from . import greeks as g

CRORE = 1e7
CONVENTIONS = {
    "classic": "Dealers long customer call OI and short customer put OI (calls +, puts -).",
    "dealer_short": "Dealers net short all customer options (calls -, puts -).",
}


def _signs(convention: str) -> tuple[float, float]:
    if convention == "classic":
        return 1.0, -1.0
    if convention == "dealer_short":
        return -1.0, -1.0
    raise ValueError(f"unknown convention {convention!r}; use one of {list(CONVENTIONS)}")


def gex_profile(spot_grid: np.ndarray, strikes: np.ndarray, ce_iv: np.ndarray, pe_iv: np.ndarray,
                ce_oi: np.ndarray, pe_oi: np.ndarray, t: float, r: float, lot: int,
                convention: str = "classic", fwd_ratio: float = 1.0) -> np.ndarray:
    """Net GEX (INR crore per 1% move) re-priced at each spot in `spot_grid` (IV held fixed)."""
    sc, sp = _signs(convention)
    S = np.asarray(spot_grid, dtype=float)[:, None]
    F = S * fwd_ratio
    ce_iv = np.nan_to_num(ce_iv, nan=0.0)
    pe_iv = np.nan_to_num(pe_iv, nan=0.0)
    with np.errstate(all="ignore"):
        gc = g.greeks(F, strikes[None, :], t, np.where(ce_iv > 0, ce_iv, np.nan), r, True)["gamma"]
        gp = g.greeks(F, strikes[None, :], t, np.where(pe_iv > 0, pe_iv, np.nan), r, False)["gamma"]
    gc, gp = np.nan_to_num(gc), np.nan_to_num(gp)
    per = (sc * gc * np.nan_to_num(ce_oi) + sp * gp * np.nan_to_num(pe_oi)) * lot * S * S * 0.01
    return per.sum(axis=1) / CRORE


def find_flip(grid: np.ndarray, profile: np.ndarray, spot: float) -> float | None:
    """Zero crossing of the net-GEX profile closest to spot (linear interpolation)."""
    s = np.sign(profile)
    idx = np.where(s[:-1] * s[1:] < 0)[0]
    if len(idx) == 0:
        return None
    flips = [grid[i] - profile[i] * (grid[i + 1] - grid[i]) / (profile[i + 1] - profile[i]) for i in idx]
    return float(min(flips, key=lambda x: abs(x - spot)))


def compute_gex(analysed: dict, lot: int, convention: str = "classic", grid_pct: float = 0.06,
                grid_n: int = 241, top_n: int = 10) -> dict:
    """Takes `chain.analyse()` output; returns GEX table, net GEX, flip, walls."""
    if not lot:
        raise ValueError("lot_size is required (from the instrument master) - refusing to guess.")
    s = analysed["summary"]
    rows = analysed["rows"]
    spot, F, t, r = s["spot"], s["forward"], s["t_years"], s["rate"]
    K = np.array([x["strike"] for x in rows])

    def arr(key):
        return np.array([np.nan if x.get(key) is None else float(x[key]) for x in rows])

    ce_iv, pe_iv = arr("ce_iv") / 100, arr("pe_iv") / 100
    ce_oi, pe_oi = arr("ce_oi"), arr("pe_oi")
    ce_g, pe_g = np.nan_to_num(arr("ce_gamma")), np.nan_to_num(arr("pe_gamma"))
    sc, sp = _signs(convention)
    unit = lot * spot * spot * 0.01 / CRORE
    ce_gex = sc * ce_g * np.nan_to_num(ce_oi) * unit
    pe_gex = sp * pe_g * np.nan_to_num(pe_oi) * unit
    net = ce_gex + pe_gex
    by_strike = [{"strike": float(k), "call_gex_cr": round(float(c), 4), "put_gex_cr": round(float(p), 4),
                  "net_gex_cr": round(float(n), 4),
                  "ce_oi": None if math.isnan(co) else co, "pe_oi": None if math.isnan(po) else po}
                 for k, c, p, n, co, po in zip(K, ce_gex, pe_gex, net, ce_oi, pe_oi, strict=True)]
    grid = np.linspace(spot * (1 - grid_pct), spot * (1 + grid_pct), grid_n)
    profile = gex_profile(grid, K, ce_iv, pe_iv, ce_oi, pe_oi, t, r, lot, convention, F / spot)
    flip = find_flip(grid, profile, spot)
    above = K >= spot
    below = K <= spot
    call_wall = float(K[above][np.argmax(np.abs(ce_gex[above]))]) if above.any() else None
    put_wall = float(K[below][np.argmax(np.abs(pe_gex[below]))]) if below.any() else None
    net_total = float(net.sum())
    regime = ("positive gamma (hedging dampens moves)" if net_total > 0
              else "negative gamma (hedging amplifies moves)")
    top = sorted(by_strike, key=lambda x: -abs(x["net_gex_cr"]))[:top_n]
    return {
        "underlying": s["underlying"], "expiry": s["expiry"], "spot": spot, "forward": F,
        "lot_size": lot, "convention": convention, "assumption": CONVENTIONS[convention],
        "units": "INR crore of index delta to hedge per 1% move in spot",
        "net_gex_cr": round(net_total, 3), "regime": regime,
        "flip_level": None if flip is None else round(flip, 1),
        "spot_vs_flip": None if flip is None else ("above" if spot > flip else "below"),
        "call_wall": call_wall, "put_wall": put_wall,
        "top_strikes": top, "by_strike": by_strike,
        "profile": {"spot": [round(float(x), 1) for x in grid[::10]],
                    "net_gex_cr": [round(float(x), 3) for x in profile[::10]]},
    }


def diff_vs_previous(cur: dict, prev: dict | None) -> dict | None:
    if not prev:
        return None
    out = {"net_gex_cr_change": round(cur["net_gex_cr"] - prev["net_gex_cr"], 3)}
    for k in ("flip_level", "call_wall", "put_wall"):
        if cur.get(k) is not None and prev.get(k) is not None:
            out[f"{k}_change"] = round(cur[k] - prev[k], 1)
    return out

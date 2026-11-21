"""Position sizing by risk budget and margin; payoff-at-expiry max loss for option structures.

Legs: {"instrument": "CE"|"PE"|"FUT", "side": "BUY"|"SELL", "strike": K, "price": premium,
       "lots": n (per 1 unit of the structure, default 1)}
"""

from __future__ import annotations

import math

import numpy as np


def _payoff(legs: list[dict], S: np.ndarray, lot: int) -> np.ndarray:
    pnl = np.zeros_like(S, dtype=float)
    for leg in legs:
        sign = 1 if leg["side"].upper() == "BUY" else -1
        n = leg.get("lots", 1) * lot
        k, px, typ = float(leg.get("strike") or 0), float(leg["price"]), leg["instrument"].upper()
        if typ == "CE":
            val = np.maximum(S - k, 0)
        elif typ == "PE":
            val = np.maximum(k - S, 0)
        else:
            val = S
        pnl += sign * (val - px) * n
    return pnl


def structure_risk(legs: list[dict], lot: int, spot: float) -> dict:
    """Exact max loss / max profit / breakevens per 1 unit of the structure at expiry.

    Expiry payoff is piecewise linear with kinks only at strikes, so extremes sit at
    {0, strikes, +inf}; the right tail is unbounded iff the net call+future slope != 0."""
    strikes = sorted({float(leg["strike"]) for leg in legs if leg.get("strike")})
    hi = max(strikes + [spot]) * 2
    pts = np.array(sorted({0.0, *strikes, hi}))
    pnl = _payoff(legs, pts, lot)
    right_slope = sum((1 if leg["side"].upper() == "BUY" else -1) * leg.get("lots", 1)
                      for leg in legs if leg["instrument"].upper() in ("CE", "FUT"))
    unlimited_up = right_slope < 0
    breakevens: list[float] = []
    for i in range(len(pts) - 1):
        a, b = pnl[i], pnl[i + 1]
        if a == 0 and pts[i] > 0:
            breakevens.append(float(pts[i]))
        elif a * b < 0:
            breakevens.append(float(pts[i] - a * (pts[i + 1] - pts[i]) / (b - a)))
    if right_slope != 0 and pnl[-1] * right_slope < 0:  # crosses zero beyond the last kink
        breakevens.append(float(pts[-1] - pnl[-1] / (right_slope * lot)))
    net_premium = sum((-1 if leg["side"].upper() == "BUY" else 1) * float(leg["price"]) * leg.get("lots", 1) * lot
                      for leg in legs if leg["instrument"].upper() in ("CE", "PE"))
    return {
        "max_loss_per_unit": None if unlimited_up else round(-min(float(pnl.min()), 0.0), 2),
        "max_profit_per_unit": None if right_slope > 0 else round(float(pnl.max()), 2),
        "unlimited_loss": unlimited_up,
        "loss_if_index_to_zero": round(-min(float(pnl[0]), 0.0), 2),
        "net_premium_per_unit": round(net_premium, 2),
        "credit_or_debit": "credit" if net_premium > 0 else "debit",
        "breakevens": sorted({round(b, 2) for b in breakevens}),
        "naked_short_legs": naked_legs(legs),
    }


def naked_legs(legs: list[dict]) -> list[str]:
    """Short options not covered by a long option of the same type (count-wise)."""
    out = []
    for typ in ("CE", "PE"):
        short = sum(leg.get("lots", 1) for leg in legs if leg["instrument"].upper() == typ and leg["side"].upper() == "SELL")
        long_ = sum(leg.get("lots", 1) for leg in legs if leg["instrument"].upper() == typ and leg["side"].upper() == "BUY")
        if short > long_:
            out.append(f"{short - long_} naked short {typ} lot(s)")
    fut_short = sum(1 for leg in legs if leg["instrument"].upper() == "FUT" and leg["side"].upper() == "SELL")
    if fut_short:
        out.append("short futures (unlimited upside risk)")
    return out


def size_position(capital: float, risk_pct: float, legs: list[dict], lot: int, spot: float,
                  margin_per_unit: float | None = None, max_margin_pct: float = 50.0,
                  cost_per_unit: float = 0.0, max_lots_cap: int | None = None) -> dict:
    risk = structure_risk(legs, lot, spot)
    budget = capital * risk_pct / 100
    warnings = []
    by_risk = None
    if risk["max_loss_per_unit"] is not None:
        per = risk["max_loss_per_unit"] + cost_per_unit
        by_risk = math.floor(budget / per) if per > 0 else None
    else:
        warnings.append("Undefined (unlimited) risk: risk-budget sizing is not possible. "
                        "Size by a stop/margin only, or add a protective wing.")
    if risk["naked_short_legs"]:
        warnings.append("Naked short exposure: " + "; ".join(risk["naked_short_legs"]))
    by_margin = None
    if margin_per_unit:
        by_margin = math.floor(capital * max_margin_pct / 100 / margin_per_unit)
    else:
        warnings.append("No margin figure supplied - run broker-margin-check for SPAN+exposure.")
    candidates = [x for x in (by_risk, by_margin, max_lots_cap) if x is not None]
    units = max(min(candidates), 0) if candidates else 0
    if units == 0:
        warnings.append("Risk budget/margin allows zero units of this structure.")
    return {
        "capital": capital, "risk_pct": risk_pct, "risk_budget": round(budget, 2), "lot_size": lot,
        "units_by_risk": by_risk, "units_by_margin": by_margin, "max_lots_cap": max_lots_cap,
        "units_allowed": units, "lots_per_leg": [leg.get("lots", 1) * units for leg in legs],
        "max_loss_at_size": None if risk["max_loss_per_unit"] is None
        else round(units * (risk["max_loss_per_unit"] + cost_per_unit), 2),
        "risk": risk, "warnings": warnings,
    }

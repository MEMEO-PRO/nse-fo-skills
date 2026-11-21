"""Black-76 pricing, Greeks and implied volatility on the forward.

Indian index options are European and cash-settled, so Black-76 on the futures /
synthetic forward is the right model: it removes the dividend-yield guesswork that
Black-Scholes on spot needs. All functions are vectorised over numpy arrays.

Conventions
- `t` in years (ACT/365, minute precision via `year_fraction`).
- `sigma` as a decimal (0.12 = 12 vol points).
- Gamma is w.r.t. the forward; for index options F ~= S*e^{(r-q)t} so spot-gamma
  differs by the factor e^{(r-q)t} (~1.0 for weeklies). We report forward gamma.
- Theta is per calendar day; vega per 1 vol point (0.01).
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
from scipy.optimize import brentq
from scipy.special import ndtr

from .session import EXPIRY_CUTOFF, IST, to_ist

_SQRT2PI = math.sqrt(2.0 * math.pi)
MIN_T = 1.0 / (365.0 * 24 * 60)  # one minute


def year_fraction(now: dt.datetime, expiry: dt.date) -> float:
    """ACT/365 year fraction from `now` (IST) to expiry at 15:30 IST, floored at one minute."""
    exp_ts = dt.datetime.combine(expiry, EXPIRY_CUTOFF, tzinfo=IST)
    secs = (exp_ts - to_ist(now)).total_seconds()
    return max(secs / (365.0 * 86400.0), MIN_T)


def _pdf(x):
    return np.exp(-0.5 * x * x) / _SQRT2PI


def _d1d2(F, K, t, sigma):
    F, K, t, sigma = (np.asarray(a, dtype=float) for a in (F, K, t, sigma))
    vs = sigma * np.sqrt(t)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F / K) + 0.5 * vs * vs) / vs
    return d1, d1 - vs, vs


def price(F, K, t, sigma, r, is_call):
    d1, d2, _ = _d1d2(F, K, t, sigma)
    df = np.exp(-np.asarray(r) * np.asarray(t))
    call = df * (F * ndtr(d1) - K * ndtr(d2))
    put = df * (K * ndtr(-d2) - F * ndtr(-d1))
    return np.where(is_call, call, put)


def greeks(F, K, t, sigma, r, is_call) -> dict[str, np.ndarray]:
    """Return price, delta, gamma, vega (per vol pt), theta (per calendar day)."""
    F = np.asarray(F, dtype=float)
    K = np.asarray(K, dtype=float)
    t = np.asarray(t, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)
    d1, d2, vs = _d1d2(F, K, t, sigma)
    df = np.exp(-r * t)
    pdf1 = _pdf(d1)
    px = price(F, K, t, sigma, r, is_call)
    delta = np.where(is_call, df * ndtr(d1), -df * ndtr(-d1))
    gamma = df * pdf1 / (F * vs)
    vega = df * F * pdf1 * np.sqrt(t) * 0.01
    theta_year = -df * F * pdf1 * sigma / (2.0 * np.sqrt(t)) + r * px
    return {"price": px, "delta": delta, "gamma": gamma, "vega": vega, "theta": theta_year / 365.0}


def implied_vol(px: float, F: float, K: float, t: float, r: float, is_call: bool,
                lo: float = 1e-4, hi: float = 5.0) -> float:
    """Implied vol by Brent's method. Returns NaN when the price violates no-arbitrage bounds."""
    if not (px > 0 and F > 0 and K > 0 and t > 0) or any(map(math.isnan, (px, F, K, t))):
        return float("nan")
    df = math.exp(-r * t)
    intrinsic = df * max(F - K, 0.0) if is_call else df * max(K - F, 0.0)
    upper = df * F if is_call else df * K
    if px <= intrinsic + 1e-9 or px >= upper:
        return float("nan")

    def f(s):
        return float(price(F, K, t, s, r, is_call)) - px

    try:
        return brentq(f, lo, hi, xtol=1e-8, maxiter=200)
    except ValueError:
        return float("nan")


def implied_vols(prices, F, strikes, t, r, is_call) -> np.ndarray:
    prices = np.atleast_1d(np.asarray(prices, dtype=float))
    strikes = np.broadcast_to(np.asarray(strikes, dtype=float), prices.shape)
    calls = np.broadcast_to(np.asarray(is_call, dtype=bool), prices.shape)
    return np.array([implied_vol(p, F, k, t, r, c) for p, k, c in zip(prices, strikes, calls, strict=True)])


def strike_for_delta(target_delta: float, F: float, t: float, sigma: float, r: float, is_call: bool) -> float:
    """Strike whose Black-76 delta equals `target_delta` (puts: pass a negative number)."""
    df = math.exp(-r * t)
    from scipy.special import ndtri

    x = target_delta / df if is_call else 1.0 + target_delta / df
    x = min(max(x, 1e-9), 1 - 1e-9)
    d1 = ndtri(x)
    vs = sigma * math.sqrt(t)
    return F * math.exp(-d1 * vs + 0.5 * vs * vs)

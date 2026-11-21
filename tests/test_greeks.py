import math

import numpy as np
import pytest

from nsefno import greeks as g


def test_black76_haug_reference():
    # Haug, "The Complete Guide to Option Pricing Formulas", Black-76 example: 1.7011
    assert float(g.price(19, 19, 0.75, 0.28, 0.10, True)) == pytest.approx(1.7011, abs=1e-4)


def test_put_call_parity():
    F, K, t, s, r = 26150.0, 26300.0, 10 / 365, 0.12, 0.055
    c = float(g.price(F, K, t, s, r, True))
    p = float(g.price(F, K, t, s, r, False))
    assert c - p == pytest.approx(math.exp(-r * t) * (F - K), abs=1e-8)


@pytest.mark.parametrize("is_call", [True, False])
@pytest.mark.parametrize("K", [25000, 26150, 27500])
def test_iv_round_trip(K, is_call):
    F, t, r = 26150.0, 5 / 365, 0.055
    for sig in (0.08, 0.15, 0.40):
        px = float(g.price(F, K, t, sig, r, is_call))
        if px < 0.05:
            continue
        assert g.implied_vol(px, F, K, t, r, is_call) == pytest.approx(sig, abs=1e-6)


def test_iv_rejects_arbitrage_violations():
    assert math.isnan(g.implied_vol(0.0, 100, 100, 0.1, 0.0, True))
    assert math.isnan(g.implied_vol(5.0, 110, 100, 0.1, 0.0, True))  # below intrinsic 10
    assert math.isnan(g.implied_vol(150.0, 100, 100, 0.1, 0.0, True))  # above forward


def test_greeks_match_finite_differences():
    F, K, t, s, r = 26150.0, 26200.0, 7 / 365, 0.11, 0.055
    h = 1.0
    gk = g.greeks(F, K, t, s, r, True)
    up, dn, mid = (float(g.price(x, K, t, s, r, True)) for x in (F + h, F - h, F))
    assert float(gk["delta"]) == pytest.approx((up - dn) / (2 * h), rel=1e-5)
    assert float(gk["gamma"]) == pytest.approx((up - 2 * mid + dn) / h**2, rel=1e-3)
    vup = float(g.price(F, K, t, s + 0.0001, r, True))
    vdn = float(g.price(F, K, t, s - 0.0001, r, True))
    assert float(gk["vega"]) == pytest.approx((vup - vdn) / 0.0002 * 0.01, rel=1e-5)
    dt_ = 1 / 365
    th = float(g.price(F, K, t - dt_, s, r, True)) - mid
    assert float(gk["theta"]) == pytest.approx(th, rel=0.05)


def test_strike_for_delta_inverts_delta():
    F, t, s, r = 26150.0, 7 / 365, 0.12, 0.055
    kc = g.strike_for_delta(0.25, F, t, s, r, True)
    kp = g.strike_for_delta(-0.25, F, t, s, r, False)
    assert float(g.greeks(F, kc, t, s, r, True)["delta"]) == pytest.approx(0.25, abs=1e-9)
    assert float(g.greeks(F, kp, t, s, r, False)["delta"]) == pytest.approx(-0.25, abs=1e-9)
    assert kp < F < kc


def test_vectorised_shapes():
    out = g.greeks(26150.0, np.array([26000, 26100, 26200]), 0.01, np.array([0.1, 0.1, 0.1]), 0.05,
                   np.array([True, False, True]))
    assert out["gamma"].shape == (3,)

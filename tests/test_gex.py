import datetime as dt
import json

import numpy as np
import pytest

from nsefno import chain, gex
from nsefno.adapters import nse_public

GOLDEN = {
    # file: (expiry, lot, net_gex_cr, flip, call_wall, put_wall) - regenerate with care.
    "nifty_2026-11-23.json": ("2026-11-23", 65),
    "banknifty_2026-11-23.json": ("2026-11-23", 30),
    "nifty_negative_gamma.json": ("2026-11-23", 65),
}


def _analysed(fix, name, lot):
    exp = dt.date.fromisoformat(GOLDEN[name][0])
    und = "BANKNIFTY" if name.startswith("bank") else "NIFTY"
    ch = nse_public.parse(json.loads((fix / name).read_text()), und, exp, lot)
    return chain.analyse(ch)


def test_gex_formula_per_strike(fix):
    a = _analysed(fix, "nifty_2026-11-23.json", 65)
    res = gex.compute_gex(a, 65)
    row = next(r for r in a["rows"] if r["strike"] == 26000)
    S = a["summary"]["spot"]
    expected_put = -row["pe_gamma"] * row["pe_oi"] * 65 * S * S * 0.01 / 1e7
    got = next(r for r in res["by_strike"] if r["strike"] == 26000)
    assert got["put_gex_cr"] == pytest.approx(expected_put, rel=1e-6)
    assert got["call_gex_cr"] > 0 > got["put_gex_cr"]


def test_net_gex_is_sum_of_strikes(fix):
    res = gex.compute_gex(_analysed(fix, "nifty_2026-11-23.json", 65), 65)
    assert res["net_gex_cr"] == pytest.approx(sum(r["net_gex_cr"] for r in res["by_strike"]), abs=0.01)


def test_flip_is_a_zero_crossing(fix):
    a = _analysed(fix, "nifty_2026-11-23.json", 65)
    res = gex.compute_gex(a, 65)
    s = a["summary"]
    K = np.array([r["strike"] for r in a["rows"]])
    col = lambda k: np.array([np.nan if r[k] is None else float(r[k]) for r in a["rows"]])  # noqa: E731
    f = res["flip_level"]
    prof = gex.gex_profile(np.array([f - 5, f + 5]), K, col("ce_iv") / 100, col("pe_iv") / 100, col("ce_oi"),
                           col("pe_oi"), s["t_years"], s["rate"], 65, "classic", s["forward"] / s["spot"])
    assert np.sign(prof[0]) != np.sign(prof[1])


def test_walls_bracket_spot(fix):
    for name, (_, lot) in GOLDEN.items():
        res = gex.compute_gex(_analysed(fix, name, lot), lot)
        assert res["put_wall"] <= res["spot"] <= res["call_wall"], name


def test_negative_gamma_fixture(fix):
    res = gex.compute_gex(_analysed(fix, "nifty_negative_gamma.json", 65), 65)
    assert res["net_gex_cr"] < 0 and "negative" in res["regime"]
    assert res["spot_vs_flip"] == "below"


def test_dealer_short_convention_is_all_negative(fix):
    res = gex.compute_gex(_analysed(fix, "nifty_2026-11-23.json", 65), 65, convention="dealer_short")
    assert all(r["net_gex_cr"] <= 0 for r in res["by_strike"])
    assert res["flip_level"] is None
    assert "short all" in res["assumption"]


def test_gex_scales_linearly_with_lot(fix):
    a = _analysed(fix, "nifty_2026-11-23.json", 65)
    assert gex.compute_gex(a, 130)["net_gex_cr"] == pytest.approx(2 * gex.compute_gex(a, 65)["net_gex_cr"], rel=1e-6)


def test_lot_size_required(fix):
    with pytest.raises(ValueError):
        gex.compute_gex(_analysed(fix, "nifty_2026-11-23.json", 65), 0)


def test_golden_snapshot(fix):
    """Regression guard: headline numbers for the synthetic NIFTY fixture."""
    res = gex.compute_gex(_analysed(fix, "nifty_2026-11-23.json", 65), 65)
    golden = json.loads((fix.parent / "golden" / "gex_nifty_2026-11-23.json").read_text())
    for k in ("net_gex_cr", "flip_level"):
        assert res[k] == pytest.approx(golden[k], rel=1e-4, abs=0.05), k
    for k in ("call_wall", "put_wall", "regime", "spot_vs_flip"):
        assert res[k] == golden[k], k

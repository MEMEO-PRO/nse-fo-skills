import pytest

from nsefno import sizer

LOT = 65


def L(side, typ, strike, price, lots=1):
    return {"side": side, "instrument": typ, "strike": strike, "price": price, "lots": lots}


def test_bull_call_spread():
    r = sizer.structure_risk([L("BUY", "CE", 26200, 82), L("SELL", "CE", 26400, 31)], LOT, 26150)
    assert r["max_loss_per_unit"] == pytest.approx(51 * LOT)
    assert r["max_profit_per_unit"] == pytest.approx((200 - 51) * LOT)
    assert r["breakevens"] == [26251.0]
    assert not r["naked_short_legs"] and r["credit_or_debit"] == "debit"


def test_iron_condor():
    legs = [L("SELL", "CE", 26400, 31), L("BUY", "CE", 26600, 8), L("SELL", "PE", 25900, 30), L("BUY", "PE", 25700, 9)]
    r = sizer.structure_risk(legs, LOT, 26150)
    credit = 31 - 8 + 30 - 9
    assert r["max_loss_per_unit"] == pytest.approx((200 - credit) * LOT)
    assert r["breakevens"] == [25900 - credit, 26400 + credit]


def test_short_strangle_is_unlimited_and_naked():
    r = sizer.structure_risk([L("SELL", "CE", 26400, 31), L("SELL", "PE", 25900, 30)], LOT, 26150)
    assert r["unlimited_loss"] and r["max_loss_per_unit"] is None
    assert r["breakevens"] == [25839.0, 26461.0]
    assert len(r["naked_short_legs"]) == 2
    s = sizer.size_position(500000, 2, [L("SELL", "CE", 26400, 31), L("SELL", "PE", 25900, 30)], LOT, 26150)
    assert s["units_allowed"] == 0 and any("unlimited" in w.lower() for w in s["warnings"])


def test_long_put_loss_capped_at_premium():
    r = sizer.structure_risk([L("BUY", "PE", 26000, 40)], LOT, 26150)
    assert r["max_loss_per_unit"] == pytest.approx(40 * LOT)
    assert r["max_profit_per_unit"] == pytest.approx((26000 - 40) * LOT)


def test_short_futures_flagged():
    r = sizer.structure_risk([{"side": "SELL", "instrument": "FUT", "price": 26200, "lots": 1}], LOT, 26150)
    assert r["unlimited_loss"]


def test_sizing_binding_constraints():
    legs = [L("BUY", "CE", 26200, 82), L("SELL", "CE", 26400, 31)]
    s = sizer.size_position(500000, 2, legs, LOT, 26150)               # 10,000 / 3,315 -> 3
    assert s["units_by_risk"] == 3 and s["units_allowed"] == 3
    s = sizer.size_position(500000, 2, legs, LOT, 26150, margin_per_unit=200000, max_margin_pct=50)
    assert s["units_by_margin"] == 1 and s["units_allowed"] == 1
    s = sizer.size_position(5_000_000, 2, legs, LOT, 26150, max_lots_cap=5)
    assert s["units_allowed"] == 5
    s = sizer.size_position(500000, 2, legs, LOT, 26150, cost_per_unit=200)
    assert s["max_loss_at_size"] == pytest.approx(s["units_allowed"] * (51 * LOT + 200))

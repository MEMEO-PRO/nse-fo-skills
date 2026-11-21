import datetime as dt

import pytest

from nsefno import costs

POST = dt.date(2026, 11, 20)   # after the 1 Apr 2026 STT hike and 1 Mar 2026 NSE txn revision
PRE = dt.date(2026, 2, 2)      # before both


def test_option_sell_leg_hand_computed():
    # SELL 130 x 120.00 on NSE, Zerodha: every line computed by hand from the published rates.
    r = costs.leg_cost(costs.Leg("CE", "SELL", 120.0, 130, "NSE"), "zerodha", POST)
    turnover = 15600.0
    stt = turnover * 0.0015                      # 23.40
    txn = turnover * 0.0003553                   # 5.54268
    sebi = turnover * 10 / 1e7                   # 0.0156
    gst = 0.18 * (20 + txn + sebi)               # 4.60049
    assert r["stt"] == pytest.approx(stt, abs=0.01)
    assert r["exchange_txn"] == pytest.approx(txn, abs=0.01)
    assert r["stamp_duty"] == 0
    assert r["gst"] == pytest.approx(gst, abs=0.01)
    assert r["total"] == pytest.approx(20 + stt + txn + sebi + gst, abs=0.01)


def test_option_buy_leg_has_stamp_not_stt():
    r = costs.leg_cost(costs.Leg("PE", "BUY", 210.0, 130, "NSE"), "zerodha", POST)
    assert r["stt"] == 0
    assert r["stamp_duty"] == pytest.approx(27300 * 0.00003, abs=0.01)


def test_stt_rates_switch_on_1_april_2026():
    leg = costs.Leg("CE", "SELL", 100.0, 1000, "NSE")
    assert costs.leg_cost(leg, "zerodha", PRE)["stt"] == pytest.approx(100.0)   # 0.10%
    assert costs.leg_cost(leg, "zerodha", POST)["stt"] == pytest.approx(150.0)  # 0.15%
    fut = costs.Leg("FUT", "SELL", 26000.0, 65, "NSE")
    assert costs.leg_cost(fut, "zerodha", PRE)["stt"] == pytest.approx(26000 * 65 * 0.0002, abs=0.01)
    assert costs.leg_cost(fut, "zerodha", POST)["stt"] == pytest.approx(26000 * 65 * 0.0005, abs=0.01)


def test_nse_txn_revision_march_2026():
    leg = costs.Leg("CE", "BUY", 100.0, 1000, "NSE")
    assert costs.leg_cost(leg, "zerodha", PRE)["exchange_txn"] == pytest.approx(35.03, abs=0.01)
    assert costs.leg_cost(leg, "zerodha", POST)["exchange_txn"] == pytest.approx(35.53, abs=0.01)


def test_bse_sensex_txn():
    r = costs.leg_cost(costs.Leg("CE", "BUY", 100.0, 1000, "BSE"), "zerodha", POST)
    assert r["exchange_txn"] == pytest.approx(32.5, abs=0.01)


def test_futures_brokerage_is_min_of_pct_and_flat():
    small = costs.leg_cost(costs.Leg("FUT", "BUY", 100.0, 10, "NSE"), "zerodha", POST)  # 0.03% of 1000 = 0.3
    big = costs.leg_cost(costs.Leg("FUT", "BUY", 26000.0, 65, "NSE"), "zerodha", POST)
    assert small["brokerage"] == pytest.approx(0.3)
    assert big["brokerage"] == 20.0


def test_kotak_neo_brokerage():
    r = costs.leg_cost(costs.Leg("CE", "BUY", 100.0, 65, "NSE"), "kotak_neo", POST)
    assert r["brokerage"] == 10.0


def test_round_trip_spread_and_breakeven():
    legs = [{"instrument": "CE", "side": "BUY", "price": 210, "qty": 130},
            {"instrument": "CE", "side": "SELL", "price": 120, "qty": 130}]
    res = costs.trade_cost(legs, "zerodha", POST)
    assert len(res["lines"]) == 4
    assert res["totals"]["brokerage"] == 80.0
    assert res["totals"]["stt"] == pytest.approx((15600 + 27300) * 0.0015, abs=0.02)
    assert res["breakeven_points"] == pytest.approx(res["totals"]["total"] / 130, abs=1e-3)
    assert res["rates_used"]["stt_effective_from"] == "2026-04-01"


def test_exercise_stt():
    assert costs.exercise_stt(50.0, 65, POST) == pytest.approx(50 * 65 * 0.0015, abs=0.01)

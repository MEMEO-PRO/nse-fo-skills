import datetime as dt

import pytest

from nsefno import calendar, session
from nsefno.session import IST


@pytest.mark.parametrize("index,nominal,actual", [
    ("NIFTY", "2026-03-03", "2026-03-02"),     # Holi (Tue)
    ("NIFTY", "2026-03-31", "2026-03-30"),     # Mahavir Jayanti (Tue, monthly)
    ("NIFTY", "2026-04-14", "2026-04-13"),     # Ambedkar Jayanti
    ("NIFTY", "2026-10-20", "2026-10-19"),     # Dussehra
    ("NIFTY", "2026-11-10", "2026-11-09"),     # Diwali Balipratipada
    ("NIFTY", "2026-11-24", "2026-11-23"),     # Guru Nanak Jayanti (monthly)
    ("SENSEX", "2026-01-15", "2026-01-14"),    # Maharashtra municipal elections (Thu)
    ("SENSEX", "2026-03-26", "2026-03-25"),    # Ram Navami (Thu, monthly)
    ("SENSEX", "2026-05-28", "2026-05-27"),    # Bakri Id (Thu, monthly)
])
def test_holiday_shifts_2026(index, nominal, actual):
    start = dt.date.fromisoformat(nominal) - dt.timedelta(days=6)
    exps = calendar.projected_expiries(index, start, 2)
    hit = [e for e in exps if e.get("shifted_from") == nominal]
    assert hit and hit[0]["expiry"] == actual


def test_projection_matches_live_master(master):
    """Rules must reproduce what the exchange actually listed (Kite dump of 21 Nov 2026)."""
    today = dt.date(2026, 11, 21)
    for index in ("NIFTY", "SENSEX"):
        projected = [e["expiry"] for e in calendar.projected_expiries(index, today, 6)]
        listed = [e.isoformat() for e in master.expiries(index) if e.isoformat() <= projected[-1]]
        assert listed and set(listed) <= set(projected), index


def test_monthly_only_indices():
    exps = calendar.projected_expiries("BANKNIFTY", dt.date(2026, 11, 21), 3)
    assert [e["expiry"] for e in exps] == ["2026-11-23", "2026-12-29", "2027-01-26"]
    assert all(e["kind"] == "monthly" for e in exps)
    assert exps[2]["holidays_verified"] is False  # 2027 list not bundled -> flagged


def test_calendar_prefers_master_and_flags_rule_mismatch(master):
    cal = calendar.expiry_calendar("BANKNIFTY", 3, dt.date(2026, 11, 21), master.expiries("BANKNIFTY"))
    assert [e["expiry"] for e in cal["expiries"]][:2] == ["2026-11-23", "2026-12-29"]
    assert cal["expiries"][0]["source"] == "instrument_master"
    assert cal["expiries"][0]["shifted_from"] == "2026-11-24"


def test_sessions_to_expiry():
    # Fri 20 Nov 2026 -> Mon 23 Nov: today (Fri) + Mon = 2 sessions
    cal = calendar.expiry_calendar("NIFTY", 1, dt.date(2026, 11, 20))
    e = cal["next_expiry"]
    assert e["expiry"] == "2026-11-23" and e["days_to_expiry"] == 3 and e["sessions_to_expiry"] == 2
    assert calendar.expiry_calendar("NIFTY", 1, dt.date(2026, 11, 23))["is_expiry_today"] is True


@pytest.mark.parametrize("ts,state", [
    ("2026-11-20T09:05:00", "pre_open"),
    ("2026-11-20T09:15:00", "open"),
    ("2026-11-20T15:29:59", "open"),
    ("2026-11-20T15:30:00", "closed"),
    ("2026-11-21T11:00:00", "weekend"),
    ("2026-11-24T11:00:00", "holiday"),
])
def test_market_state(ts, state):
    assert session.market_state(dt.datetime.fromisoformat(ts).replace(tzinfo=IST))["state"] == state


def test_trading_day_helpers():
    assert session.previous_trading_day(dt.date(2026, 11, 25)) == dt.date(2026, 11, 23)
    assert session.next_trading_day(dt.date(2026, 11, 20)) == dt.date(2026, 11, 23)
    assert session.trading_days_between(dt.date(2026, 11, 20), dt.date(2026, 11, 27)) == 4

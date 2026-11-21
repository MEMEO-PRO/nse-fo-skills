import datetime as dt

import pytest

from nsefno import journal


def test_plan_fill_review(tmp_path):
    con = journal.connect(tmp_path / "j.sqlite")
    p1 = journal.add_plan(con, "bull-call", "NIFTY", [{"leg": "x"}], created_at="2026-11-16T09:30:00")
    journal.add_fill(con, p1, "2026-11-16T09:31:00", "NIFTY26NOV26200CE", "BUY", 65, 82.5, planned_price=82.0)
    journal.add_fill(con, p1, "2026-11-18T14:00:00", "NIFTY26NOV26200CE", "SELL", 65, 120.0, planned_price=120.0)
    p2 = journal.add_plan(con, "short-straddle", "NIFTY", [], created_at="2026-11-17T09:30:00")
    journal.add_fill(con, p2, "2026-11-17T09:31:00", "NIFTY26NOV26150PE", "SELL", 65, 100.0)
    journal.add_fill(con, p2, "2026-11-17T15:00:00", "NIFTY26NOV26150PE", "BUY", 65, 130.0)
    p3 = journal.add_plan(con, "open-one", "NIFTY", [], created_at="2026-11-18T10:00:00")
    journal.add_fill(con, p3, "2026-11-18T10:00:00", "NIFTY26DEC26500CE", "BUY", 65, 50.0)
    r = journal.weekly_review(con, dt.date(2026, 11, 16), dt.date(2026, 11, 22))
    assert r["trades_closed"] == 2 and r["trades_open"] == 1
    assert r["win_rate_pct"] == 50.0
    t1 = next(t for t in r["trades"] if t["plan_id"] == p1)
    assert t1["gross_pnl"] == pytest.approx((120 - 82.5) * 65)
    assert t1["slippage_inr"] == pytest.approx(0.5 * 65)    # paid 0.5 more than planned
    assert t1["net_pnl"] == pytest.approx(t1["gross_pnl"] - t1["costs"])
    assert r["gross_pnl"] == pytest.approx((120 - 82.5) * 65 - 30 * 65)
    assert r["cost_drag_pct_of_gross"] > 0
    assert set(r["by_tag"]) == {"bull-call", "short-straddle"}


def test_tradebook_import_is_idempotent(tmp_path):
    csv_path = tmp_path / "tb.csv"
    csv_path.write_text(
        "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,"
        "order_execution_time\n"
        "NIFTY26NOV26200CE,,2026-11-16,NFO,FO,,buy,false,65,82.5,T1,O1,2026-11-16 09:31:00\n"
        "NIFTY26NOV26200CE,,2026-11-18,NFO,FO,,sell,false,65,120,T2,O2,2026-11-18 14:00:00\n")
    con = journal.connect(tmp_path / "j.sqlite")
    assert journal.import_kite_tradebook(con, str(csv_path)) == 2
    assert journal.import_kite_tradebook(con, str(csv_path)) == 0

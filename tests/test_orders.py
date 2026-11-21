import datetime as dt
import json
import time

import pytest

from nsefno import orders
from nsefno.errors import ComplianceBlock
from nsefno.session import IST

OPEN = dt.datetime(2026, 11, 20, 11, 0, tzinfo=IST)
PRE_OPEN = dt.datetime(2026, 11, 20, 9, 5, tzinfo=IST)
CFG = {"broker": "kite", "max_lots_per_leg": 10, "algo_id": "GEN123", "static_ip": "203.0.113.7",
       "product": "NRML", "orders_per_second": 8}
PLAN = [{"instrument": "NIFTY 23 Nov 26200 CE", "side": "BUY", "lots": 3, "price": 82.05},
        {"instrument": "NIFTY 23 Nov 26400 CE", "side": "SELL", "lots": 3, "price": 31.10}]


@pytest.mark.parametrize("qty,lot,freeze,expected", [
    (195, 65, 1800, [195]),
    (3900, 65, 1800, [1755, 1755, 390]),     # 27 lots max per slice (< 1800)
    (1755, 65, 1756, [1755]),                 # exactly one below freeze
    (1820, 65, 1820, [1755, 65]),             # equal to freeze -> sliced (strictly below)
    (600, 30, None, [600]),
])
def test_slice_quantity(qty, lot, freeze, expected):
    assert orders.slice_quantity(qty, lot, freeze) == expected
    assert sum(expected) == qty


def test_slice_rejects_non_lot_qty():
    with pytest.raises(ComplianceBlock):
        orders.slice_quantity(100, 65, 1800)


def test_price_checks():
    assert orders.check_price(82.05, 0.05, (10.0, 200.0), "LIMIT") == []
    with pytest.raises(ComplianceBlock, match="tick"):
        orders.check_price(82.03, 0.05, None, "LIMIT")
    with pytest.raises(ComplianceBlock, match="band"):
        orders.check_price(250.0, 0.05, (10.0, 200.0), "LIMIT")
    assert orders.check_price(None, 0.05, None, "MARKET")  # warns


def test_prepare_dry_run_open_market(master):
    res = orders.prepare(PLAN, master, CFG, freeze={"NIFTY": 1800}, now=OPEN)
    assert res["mode"] == "dry_run" and res["n_orders"] == 2
    assert res["orders"][0] == {"exchange": "NFO", "tradingsymbol": "NIFTY26NOV26200CE", "transaction_type": "BUY",
                                "quantity": 195, "order_type": "LIMIT", "product": "NRML", "validity": "DAY",
                                "price": 82.05, "tag": "GEN123"}
    assert res["confirm_token"]


def test_prepare_blocks_send_in_pre_open(master):
    res = orders.prepare(PLAN, master, CFG, now=PRE_OPEN)
    assert res["confirm_token"] is None
    assert any("pre_open" in w for w in res["warnings"])
    assert any("freeze" in w.lower() for w in res["warnings"])


def test_max_lots_cap(master):
    with pytest.raises(ComplianceBlock, match="max_lots_per_leg"):
        orders.prepare([{**PLAN[0], "lots": 11}], master, CFG, now=OPEN)


def test_token_binds_payload_and_expires():
    o = [{"tradingsymbol": "X", "quantity": 65}]
    tok = orders.issue_token(o)
    orders.verify_token(tok, o)
    with pytest.raises(ComplianceBlock, match="match"):
        orders.verify_token(tok, [{"tradingsymbol": "X", "quantity": 650}])
    with pytest.raises(ComplianceBlock, match="expired"):
        orders.verify_token(tok, o, now=time.time() + 61)
    with pytest.raises(ComplianceBlock, match="Malformed"):
        orders.verify_token("garbage", o)


def test_send_requires_open_market_and_valid_token(master):
    res = orders.prepare(PLAN, master, CFG, now=OPEN)
    sent = []
    with pytest.raises(ComplianceBlock, match="closed"):
        orders.send(res["orders"], res["confirm_token"], now=dt.datetime(2026, 11, 20, 16, 0, tzinfo=IST),
                    sender=sent.append)
    with pytest.raises(ComplianceBlock):
        orders.send(res["orders"], "1.deadbeef", now=OPEN, sender=sent.append)
    assert sent == []
    out = orders.send(res["orders"], res["confirm_token"], now=OPEN, sender=lambda o: {"order_id": "1"})
    assert [r["status"] for r in out] == ["sent", "sent"]


def test_send_stops_on_first_error(master):
    res = orders.prepare(PLAN, master, CFG, now=OPEN)

    def boom(o):
        raise RuntimeError("RMS rejected")

    out = orders.send(res["orders"], res["confirm_token"], now=OPEN, sender=boom)
    assert len(out) == 1 and out[0]["status"] == "error"


def test_rate_limiter_never_exceeds_window():
    clock = {"t": 0.0}
    stamps = []

    def sleep(s):
        clock["t"] += s

    rl = orders.RateLimiter(8, clock=lambda: clock["t"], sleep=sleep)
    for _ in range(40):
        rl.acquire()
        stamps.append(clock["t"])
    for i in range(len(stamps)):
        assert sum(1 for s in stamps if stamps[i] <= s < stamps[i] + 1.0) <= 8


def test_config_rejects_10_ops(tmp_path, monkeypatch):
    from nsefno.config import home

    (home() / "config.yaml").write_text("orders_per_second: 10\n")
    with pytest.raises(ComplianceBlock):
        orders.load_config()


def test_orders_log_is_redacted(master):
    orders.prepare(PLAN, master, {**CFG, "api_key": "SECRET"}, now=OPEN)
    from nsefno.config import home

    log = (home() / "logs" / "orders.jsonl").read_text()
    assert "NIFTY26NOV26200CE" in log and "SECRET" not in log
    json.loads(log.splitlines()[-1])

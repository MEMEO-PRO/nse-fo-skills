import datetime as dt
import json

import numpy as np
import pytest

from nsefno import chain
from nsefno.adapters import local_store, nse_public
from nsefno.envelope import ensure_fresh
from nsefno.errors import AdapterError, StaleDataError
from nsefno.session import IST


@pytest.fixture
def nifty(fix):
    payload = json.loads((fix / "nifty_2026-11-23.json").read_text())
    return nse_public.parse(payload, "NIFTY", dt.date(2026, 11, 23), 65)


def test_parse_nse_layout(nifty):
    assert nifty.spot == 26152.35 and nifty.lot_size == 65 and len(nifty.rows) == 81
    assert nifty.fetched_at == dt.datetime(2026, 11, 20, 15, 30, tzinfo=IST)
    assert nifty.meta["oi_unit"] == "contracts"
    assert {"ce_bid", "ce_ask", "pe_oi", "pe_doi"} <= set(nifty.rows[0])


def test_parse_rejects_wrong_expiry(fix):
    payload = json.loads((fix / "nifty_2026-11-23.json").read_text())
    with pytest.raises(AdapterError):
        nse_public.parse(payload, "NIFTY", dt.date(2026, 12, 1), 65)


def test_infer_expiry(fix):
    payload = json.loads((fix / "nifty_2026-12-01.json").read_text())
    assert nse_public.infer_expiry(payload) == dt.date(2026, 12, 1)


def test_analyse_recovers_generator_parameters(nifty):
    a = chain.analyse(nifty)
    s = a["summary"]
    # Generator used spot*e^{rt} with r=5.5% - parity forward must land within a point.
    t = s["t_years"]
    assert s["forward"] == pytest.approx(26152.35 * np.exp(0.055 * t), abs=1.5)
    assert s["forward_source"] == "put_call_parity"
    assert s["atm_iv"] == pytest.approx(10.5, abs=0.15)
    assert s["atm_strike"] == 26150.0
    assert s["days_to_expiry"] == pytest.approx(3.0, abs=1e-6)
    # Expected move = F * iv * sqrt(t)
    assert s["expected_move_1sd"] == pytest.approx(s["forward"] * s["atm_iv"] / 100 * np.sqrt(t), abs=1)


def test_max_pain_brute_force():
    K = np.array([100.0, 110, 120, 130])
    ce = np.array([10.0, 50, 100, 10])
    pe = np.array([80.0, 60, 10, 5])
    pain = {k: sum(ce * np.maximum(k - K, 0)) + sum(pe * np.maximum(K - k, 0)) for k in K}
    assert chain.max_pain(K, ce, pe) == min(pain, key=pain.get)


def test_pcr(nifty):
    s = chain.analyse(nifty)["summary"]
    assert s["pcr_oi"] == pytest.approx(s["total_pe_oi_contracts"] / s["total_ce_oi_contracts"], abs=1e-3)


def test_stale_chain_is_refused(nifty):
    stale_after = (nifty.fetched_at + dt.timedelta(seconds=nifty.stale_after_s)).isoformat()
    with pytest.raises(StaleDataError):
        ensure_fresh({"stale_after": stale_after}, now=nifty.fetched_at + dt.timedelta(minutes=5))
    ensure_fresh({"stale_after": stale_after}, now=nifty.fetched_at + dt.timedelta(seconds=30))


def test_snapshot_round_trip_and_previous(nifty):
    p1 = local_store.save_chain(nifty)
    later = chain.OptionChain.from_dict(nifty.to_dict())
    later.fetched_at = nifty.fetched_at + dt.timedelta(minutes=15)
    local_store.save_chain(later)
    prev = local_store.previous_chain(later)
    assert prev is not None and prev.fetched_at == nifty.fetched_at
    assert local_store.load_chain(p1).rows == nifty.rows


def test_parquet_export(nifty, tmp_path):
    pytest.importorskip("pyarrow")
    out = local_store.export_parquet(nifty, tmp_path / "c.parquet")
    import pyarrow.parquet as pq

    assert pq.read_table(out).num_rows == len(nifty.rows)

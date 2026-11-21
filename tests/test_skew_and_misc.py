import datetime as dt
import json

import pytest

from nsefno import chain, resources, skew
from nsefno.adapters import nse_archives, nse_public
from nsefno.config import redact


def _a(fix, name, exp):
    return chain.analyse(nse_public.parse(json.loads((fix / name).read_text()), "NIFTY", exp, 65))


def test_skew_signs_and_term_structure(fix):
    a1 = _a(fix, "nifty_2026-11-23.json", dt.date(2026, 11, 23))
    a2 = _a(fix, "nifty_2026-12-29.json", dt.date(2026, 12, 29))
    m1, m2 = skew.skew_metrics(a1), skew.skew_metrics(a2)
    assert m1["rr_25d"] < 0 and m1["bf_25d"] > 0          # generator has put skew + convexity
    assert m1["put_25d_iv"] > m1["atm_iv"] > m1["call_25d_iv"]
    assert skew.term_structure([m1, m2])["shape"].startswith("contango")


def test_otm_smile_switches_side_at_forward(fix):
    a = _a(fix, "nifty_2026-11-23.json", dt.date(2026, 11, 23))
    sm = skew.otm_smile(a)
    F = a["summary"]["forward"]
    assert all((p["side"] == "PE") == (p["strike"] < F) for p in sm)


def test_iv_percentile():
    hist = [10 + i * 0.1 for i in range(100)]   # 10.0 .. 19.9
    r = skew.iv_percentile(15.0, hist)
    assert r["iv_percentile"] == 50.0 and r["iv_rank"] == pytest.approx(50.5, abs=0.1)
    assert skew.iv_percentile(15.0, hist[:5])["iv_percentile"] is None


def test_bhavcopy_atm_iv(fix):
    rows = nse_archives.parse_bhavcopy((fix / "bhavcopy_NSE_FO_20261120_sample.csv").read_text(), "NIFTY")
    assert all(r["lot_size"] == 65 for r in rows)
    rec = nse_archives.atm_iv_from_bhavcopy(rows)
    assert rec["expiry"] == "2026-11-23" and rec["atm_strike"] == 26150
    assert rec["atm_iv"] == pytest.approx(10.5, abs=0.3)   # generator vol, ticks rounding
    rec2 = nse_archives.atm_iv_from_bhavcopy(rows, min_days=4)
    assert rec2["expiry"] == "2026-12-01" and rec2["atm_iv"] == pytest.approx(11.8, abs=0.3)


def test_charges_reviewed_recently():
    reviewed = resources.charges()["reviewed_on"]
    age = (dt.date.today() - reviewed).days
    assert age <= 90, f"charges.yaml reviewed {age} days ago - re-verify STT/exchange/SEBI/stamp rates"


def test_every_rate_has_source_and_date():
    c = resources.charges()
    for key in ("stt", "sebi_fee", "stamp_duty", "gst"):
        for e in c[key]:
            assert e["source"] and e["effective_from"]
    for ex in c["exchange_txn"].values():
        for e in ex:
            assert e["source"] and e["effective_from"]


def test_redaction():
    out = redact({"api_key": "k", "access_token": "t", "instrument_token": "123", "nested": [{"password": "p"}],
                  "price": 10})
    assert out == {"api_key": "***", "access_token": "***", "instrument_token": "123",
                   "nested": [{"password": "***"}], "price": 10}

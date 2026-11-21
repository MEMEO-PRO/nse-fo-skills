import datetime as dt

import pytest

from nsefno.adapters import kotak_neo
from nsefno.errors import InstrumentNotFound


def test_lot_sizes_come_from_master(master):
    assert master.lot_size("NIFTY", dt.date(2026, 11, 23)) == 65
    assert master.lot_size("BANKNIFTY", dt.date(2026, 11, 23)) == 30


def test_lot_size_transition_is_per_series(master):
    # SENSEX: 20 in the Nov/Dec-2026 series, 25 from the Jan-2027 series (live master, 21 Nov 2026)
    assert master.lot_size("SENSEX", dt.date(2026, 11, 26)) == 20
    assert master.lot_size("SENSEX", dt.date(2027, 1, 28)) == 25


@pytest.mark.parametrize("text,symbol", [
    ("NIFTY 23 Nov 26000 CE", "NIFTY26NOV26000CE"),
    ("nifty 26000 ce", "NIFTY26NOV26000CE"),
    ("NIFTY 2026-12-01 26000 PE", "NIFTY26D0126000PE"),
    ("NIFTY 1-DEC-2026 26000 call", "NIFTY26D0126000CE"),
    ("BANKNIFTY monthly 59000 PE", "BANKNIFTY26NOV59000PE"),
    ("NIFTY DEC 26000 CE", "NIFTY26DEC26000CE"),
    ("NIFTY FUT", "NIFTY26NOVFUT"),
    ("NIFTY26NOV26000CE", "NIFTY26NOV26000CE"),
    ("SENSEX 85000 CE", "SENSEX26NOV85000CE"),
])
def test_resolve(master, text, symbol):
    assert master.resolve(text, dt.date(2026, 11, 21)).tradingsymbol == symbol


def test_resolve_wrong_expiry_explains_holiday_shift(master):
    with pytest.raises(InstrumentNotFound, match="2026-11-23"):
        master.resolve("NIFTY 24 Nov 26000 CE", dt.date(2026, 11, 21))


def test_resolve_unlisted_strike_suggests_nearest(master):
    with pytest.raises(InstrumentNotFound, match="Nearest listed strikes"):
        master.resolve("NIFTY 23 Nov 26025 CE", dt.date(2026, 11, 21))


def test_resolve_requires_option_type(master):
    with pytest.raises(InstrumentNotFound):
        master.resolve("NIFTY 26000", dt.date(2026, 11, 21))


def test_kotak_neo_scrip_master_quirks(fix):
    items = kotak_neo.parse_scrip_master((fix / "kotak_neo_scrip_master_sample.csv").read_text())
    by = {i.tradingsymbol: i for i in items}
    ce = by["NIFTY26NOV26000CE"]
    assert ce.expiry == dt.date(2026, 11, 23)          # 1980-epoch offset handled
    assert ce.strike == 26000.0                        # paise -> rupees
    assert ce.tick_size == pytest.approx(0.05)
    assert ce.freeze_qty == 1756 and ce.lot_size == 65
    assert by["SENSEX26N2685000CE"].expiry == dt.date(2026, 11, 26)  # bse_fo plain unix epoch
    assert by["SENSEX26N2685000CE"].exchange == "BFO"
    assert by["NIFTY26NOVFUT"].strike == 0.0
    assert "RELIANCE-EQ" not in by

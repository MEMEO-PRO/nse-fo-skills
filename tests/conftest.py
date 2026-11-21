import datetime as dt
from pathlib import Path

import pytest

from nsefno.adapters import kite
from nsefno.instruments import InstrumentMaster

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.nsefno during tests."""
    monkeypatch.setenv("NSEFNO_HOME", str(tmp_path / "nsefno_home"))


@pytest.fixture
def fix():
    return FIX


@pytest.fixture
def master():
    items = kite.parse_instruments_csv((FIX / "kite_NFO_sample.csv").read_text(), "NFO")
    items += kite.parse_instruments_csv((FIX / "kite_BFO_sample.csv").read_text(), "BFO")
    return InstrumentMaster(items, source="fixture", as_of=dt.date(2026, 11, 21))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests must never reach a broker/exchange. Mocks patch Broker._request or session.get explicitly."""
    import requests

    def blocked(self, method, url, *a, **k):
        raise RuntimeError(f"network disabled in tests: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", blocked)

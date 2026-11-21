"""Broker registry. `get_broker(name)` returns an adapter implementing `brokers.base.Broker`."""

from __future__ import annotations

from ..errors import ConfigError
from .aliceblue import AliceBlue
from .angel import Angel
from .base import Broker, NotSupported, OrderIntent
from .breeze import Breeze
from .dhan import Dhan
from .fivepaisa import FivePaisa
from .fyers import Fyers
from .groww import Groww
from .kite import Kite
from .kotak_neo import KotakNeo
from .shoonya import Shoonya
from .upstox import Upstox
from .xts import XTS

REGISTRY: dict[str, type[Broker]] = {b.name: b for b in (
    Kite, Upstox, Dhan, Fyers, Angel, Groww, Shoonya, Breeze, FivePaisa, AliceBlue, KotakNeo, XTS)}
ALIASES = {"zerodha": "kite", "kite_public": "kite", "angelone": "angel", "smartapi": "angel", "finvasia": "shoonya",
           "icici": "breeze", "icicidirect": "breeze", "5paisa": "fivepaisa", "alice": "aliceblue", "kotak": "kotak_neo",
           "neo": "kotak_neo", "iifl": "xts", "symphony": "xts"}


def get_broker(name: str) -> Broker:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in REGISTRY:
        raise ConfigError(f"Unknown broker {name!r}. Available: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[key]()


__all__ = ["REGISTRY", "get_broker", "Broker", "OrderIntent", "NotSupported"]

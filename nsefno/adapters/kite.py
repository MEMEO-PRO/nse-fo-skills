"""Backward-compatible shim: the Kite adapter now lives in nsefno.brokers.kite."""

from __future__ import annotations

from ..brokers.kite import Kite
from ..errors import AdapterError
from ..instruments import Instrument, InstrumentMaster


def parse_instruments_csv(text: str, exchange: str) -> list[Instrument]:
    out = Kite().parse_master(text, exchange)
    if not out:
        raise AdapterError(f"Kite instruments dump for {exchange} parsed to zero derivatives - format changed?")
    return out


def load_instruments(ttl: float = 6 * 3600) -> InstrumentMaster:
    m = Kite().load_master(ttl)
    m.source = "kite_public"
    return m


def quotes(keys: list[str]) -> dict:
    return Kite().quotes(keys)


def basket_margin(orders: list[dict], consider_positions: bool = True) -> dict:
    return Kite().basket_margin(orders)


def place_order(payload: dict, variety: str = "regular") -> dict:
    return Kite().place_order(payload)

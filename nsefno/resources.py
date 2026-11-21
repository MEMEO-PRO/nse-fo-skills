"""Loaders for packaged reference data (charges, holidays, index rules)."""

from __future__ import annotations

import datetime as dt
from functools import cache
from importlib import resources
from typing import Any

import yaml


def _load(name: str) -> Any:
    with resources.files("nsefno.data").joinpath(name).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@cache
def charges() -> dict:
    return _load("charges.yaml")


@cache
def index_rules() -> dict[str, dict]:
    return _load("indices.yaml")


@cache
def _holidays_raw() -> dict:
    return _load("holidays.yaml")


def holiday_years(exchange: str) -> set[int]:
    raw = _holidays_raw().get(exchange.upper(), {})
    return {int(y) for y in raw}


@cache
def holidays(exchange: str) -> dict[dt.date, str]:
    """Return {date: name} for every published year of `exchange`."""
    raw = _holidays_raw()
    ex = exchange.upper()
    out: dict[dt.date, str] = {}
    for _year, block in raw.get(ex, {}).items():
        if "same_as" in block:
            src = raw[block["same_as"]].get(_year, {})
            dates = src.get("dates", {})
        else:
            dates = block.get("dates", {})
        for d, name in dates.items():
            out[d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))] = name
    return out


# Broker-specific names for the same underlying (verified against each broker's master file).
UNDERLYING_ALIASES = {
    "NIFTY50": "NIFTY", "NIFTYBANK": "BANKNIFTY", "MIDCAPNIFTY": "MIDCPNIFTY", "NIFTYNEXT50": "NIFTYNXT50",
    "NIFTYFINSERVICE": "FINNIFTY", "NIFTYMIDSELECT": "MIDCPNIFTY",
    # ICICI Breeze stock codes
    "CNXBAN": "BANKNIFTY", "NIFFIN": "FINNIFTY", "NIFSEL": "MIDCPNIFTY", "NIFNEX": "NIFTYNXT50",
    "BSESEN": "SENSEX",
    # BSE product codes used by Shoonya / Dhan
    "BSXOPT": "SENSEX", "BSXFUT": "SENSEX", "BKXOPT": "BANKEX", "BKXFUT": "BANKEX",
    "SX50OPT": "SENSEX50", "SX50FUT": "SENSEX50",
}


def normalise_underlying(name: str) -> str:
    key = (name or "").upper().replace(" ", "").replace("_", "")
    return UNDERLYING_ALIASES.get(key, (name or "").upper().strip())


def index_rule(index: str) -> dict:
    rules = index_rules()
    key = normalise_underlying(index)
    if key not in rules:
        raise KeyError(f"Unknown index {index!r}. Known: {', '.join(rules)}")
    return {"index": key, **rules[key]}

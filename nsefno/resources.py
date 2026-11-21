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


def index_rule(index: str) -> dict:
    rules = index_rules()
    key = index.upper().replace(" ", "")
    aliases = {"NIFTY50": "NIFTY", "BANK NIFTY": "BANKNIFTY", "NIFTYBANK": "BANKNIFTY",
               "FINNIFTY": "FINNIFTY", "MIDCAPNIFTY": "MIDCPNIFTY", "NIFTYNEXT50": "NIFTYNXT50"}
    key = aliases.get(key, key)
    if key not in rules:
        raise KeyError(f"Unknown index {index!r}. Known: {', '.join(rules)}")
    return {"index": key, **rules[key]}

"""Kotak Neo adapter (Trade API v2 / `neo_api_client`).

Scrip master: the Neo API returns per-segment CSV URLs (nse_fo.csv, bse_fo.csv).
Known format quirks handled here:
  * `lExpiryDate` for nse_fo is seconds since 1980-01-01 (add 315511200 to get Unix time);
    bse_fo uses plain Unix time.
  * `dStrikePrice;` (sic, trailing semicolon in header) is in paise -> divide by 100.
  * `lFreezeQty` (if present) gives the exchange freeze quantity.
Column names are mapped in COLS so a format change is a one-line fix.
Auth (orders/margins) goes through the official SDK when installed; credentials come
from env: NEO_CONSUMER_KEY, NEO_MOBILE, NEO_UCC, NEO_MPIN, NEO_TOTP (never files).
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from ..errors import AdapterError, ConfigError
from ..instruments import Instrument, InstrumentMaster
from ..session import now_ist

EPOCH_1980_OFFSET = 315511200
COLS = {
    "symbol": "pSymbolName", "trdsym": "pTrdSymbol", "token": "pSymbol", "inst_type": "pInstType",
    "opt": "pOptionType", "strike": ("dStrikePrice;", "dStrikePrice"), "lot": "lLotSize",
    "expiry": "lExpiryDate", "tick": "dTickSize", "freeze": "lFreezeQty", "seg": "pExchSeg",
}
SEG_TO_EX = {"nse_fo": "NFO", "bse_fo": "BFO"}


def _get(row: dict, key):
    if isinstance(key, tuple):
        for k in key:
            if k in row:
                return row[k]
        return None
    return row.get(key)


def _expiry(raw: str, seg: str) -> dt.date:
    """nse_fo/cde_fo count seconds from 1980-01-01; bse_fo uses Unix time. If the segment rule
    yields a date years in the past (format drift), fall back to the other epoch."""
    secs = int(float(raw))
    offset = EPOCH_1980_OFFSET if seg in ("nse_fo", "cde_fo") else 0
    d = dt.datetime.fromtimestamp(secs + offset, tz=dt.UTC).date()
    if d.year < dt.date.today().year - 5:
        d = dt.datetime.fromtimestamp(secs + (EPOCH_1980_OFFSET - offset), tz=dt.UTC).date()
    return d


def parse_scrip_master(text: str) -> list[Instrument]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        inst = (_get(r, COLS["inst_type"]) or "").upper()
        if inst not in ("OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK", "IO", "IF"):
            continue
        opt = (_get(r, COLS["opt"]) or "").upper()
        itype = opt if opt in ("CE", "PE") else "FUT"
        seg = (_get(r, COLS["seg"]) or "nse_fo").lower()
        tick_raw = float(_get(r, COLS["tick"]) or 5)
        freeze = _get(r, COLS["freeze"])
        out.append(Instrument(
            exchange=SEG_TO_EX.get(seg, seg.upper()), underlying=(_get(r, COLS["symbol"]) or "").upper(),
            instrument_type=itype, expiry=_expiry(_get(r, COLS["expiry"]), seg),
            strike=float(_get(r, COLS["strike"]) or 0) / 100.0 if itype != "FUT" else 0.0,
            lot_size=int(float(_get(r, COLS["lot"]))), tick_size=tick_raw / 100.0,
            tradingsymbol=_get(r, COLS["trdsym"]), token=str(_get(r, COLS["token"])),
            freeze_qty=int(float(freeze)) if freeze not in (None, "", "0") else None, source="kotak_neo",
        ))
    if not out:
        raise AdapterError("Kotak Neo scrip master parsed to zero derivatives - check COLS mapping.")
    return out


def load_instruments_from_csv(paths: list[str]) -> InstrumentMaster:
    items: list[Instrument] = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            items.extend(parse_scrip_master(fh.read()))
    return InstrumentMaster(items, source="kotak_neo", as_of=now_ist().date())


def client():
    """Return a logged-in neo_api_client.NeoAPI (requires `pip install neo_api_client`)."""
    try:
        from neo_api_client import NeoAPI  # type: ignore
    except ImportError as e:
        raise ConfigError("Install the official Kotak Neo SDK: pip install neo_api_client") from e
    from ..config import secret

    c = NeoAPI(environment="prod", consumer_key=secret("NEO_CONSUMER_KEY"))
    c.totp_login(mobile_number=secret("NEO_MOBILE"), ucc=secret("NEO_UCC"), totp=secret("NEO_TOTP"))
    c.totp_validate(mpin=secret("NEO_MPIN"))
    return c

"""Expiry calendar for NSE/BSE index derivatives.

Authoritative source = the day's instrument master (exchange-published contract list).
Rules are used only to project beyond the master or when offline, and every projected
date is labelled `source: rules` with `holidays_verified` telling whether the official
holiday list for that year is bundled.
"""

from __future__ import annotations

import calendar as _cal
import datetime as dt
from collections.abc import Iterable

from . import resources, session

_WEEKDAY = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}


def _last_weekday_of_month(year: int, month: int, weekday: int) -> dt.date:
    last = dt.date(year, month, _cal.monthrange(year, month)[1])
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _shift_for_holiday(nominal: dt.date, exchange: str) -> dt.date:
    d = nominal
    while not session.is_trading_day(d, exchange):
        d -= dt.timedelta(days=1)
    return d


def _entry(index: str, nominal: dt.date, actual: dt.date, kind: str, exchange: str,
           today: dt.date, source: str) -> dict:
    e = {
        "index": index,
        "expiry": actual.isoformat(),
        "weekday": actual.strftime("%a"),
        "kind": kind,
        "days_to_expiry": (actual - today).days,
        "sessions_to_expiry": session.trading_days_between(today, actual, exchange)
        + (1 if session.is_trading_day(today, exchange) and actual >= today else 0),
        "source": source,
        "holidays_verified": session.holidays_verified(actual, exchange),
    }
    if actual != nominal:
        e["shifted_from"] = nominal.isoformat()
        e["shift_reason"] = session.holiday_name(nominal, exchange) or "non-trading day"
    return e


def projected_expiries(index: str, start: dt.date, n: int = 6) -> list[dict]:
    """Rule-based projection of the next `n` expiries on/after `start`."""
    rule = resources.index_rule(index)
    ex, wd = rule["exchange"], _WEEKDAY[rule["expiry_weekday"]]
    out: list[dict] = []
    seen: set[dt.date] = set()

    def monthly_nominal(y: int, m: int) -> dt.date:
        return _last_weekday_of_month(y, m, wd)

    y, m = start.year, start.month
    if rule["weekly"]:
        d = start - dt.timedelta(days=7)
        d += dt.timedelta(days=(wd - d.weekday()) % 7)
        while len(out) < n:
            actual = _shift_for_holiday(d, ex)
            if actual >= start and actual not in seen:
                kind = "monthly" if d == monthly_nominal(d.year, d.month) else "weekly"
                out.append(_entry(rule["index"], d, actual, kind, ex, start, "rules"))
                seen.add(actual)
            d += dt.timedelta(days=7)
    else:
        while len(out) < n:
            nominal = monthly_nominal(y, m)
            actual = _shift_for_holiday(nominal, ex)
            if actual >= start:
                out.append(_entry(rule["index"], nominal, actual, "monthly", ex, start, "rules"))
            m += 1
            if m == 13:
                y, m = y + 1, 1
    return out


def expiries_from_master(index: str, dates: Iterable[dt.date], start: dt.date, n: int = 6) -> list[dict]:
    """Label exchange-listed expiry dates (from the instrument master)."""
    rule = resources.index_rule(index)
    ex = rule["exchange"]
    ds = sorted({d for d in dates if d >= start})
    by_month: dict[tuple[int, int], dt.date] = {}
    for d in sorted(set(dates)):
        by_month[(d.year, d.month)] = max(by_month.get((d.year, d.month), d), d)
    out = []
    for d in ds[:n]:
        kind = "monthly" if by_month[(d.year, d.month)] == d else "weekly"
        nominal = d
        # Recover the nominal (pre-holiday-shift) date for transparency.
        wd = _WEEKDAY[rule["expiry_weekday"]]
        if d.weekday() != wd:
            cand = d + dt.timedelta(days=(wd - d.weekday()) % 7)
            if not session.is_trading_day(cand, ex):
                nominal = cand
        out.append(_entry(rule["index"], nominal, d, kind, ex, start, "instrument_master"))
    return out


def expiry_calendar(index: str, n: int = 6, today: dt.date | None = None,
                    master_dates: Iterable[dt.date] | None = None) -> dict:
    today = today or session.now_ist().date()
    rule = resources.index_rule(index)
    if master_dates:
        items = expiries_from_master(index, master_dates, today, n)
        projected = {e["expiry"] for e in projected_expiries(index, today, n)}
        mismatches = [e["expiry"] for e in items if e["expiry"] not in projected and e["kind"] == "weekly"]
    else:
        items = projected_expiries(index, today, n)
        mismatches = []
    nxt = items[0] if items else None
    warnings = []
    if not all(e["holidays_verified"] for e in items):
        warnings.append("Some projected dates fall in a year whose official holiday list is not bundled; "
                        "confirm against the instrument master / exchange circular.")
    if mismatches:
        warnings.append(f"Master expiries not matching the rule set: {mismatches} (special/holiday shifts).")
    return {
        "index": rule["index"],
        "exchange": rule["exchange"],
        "today": today.isoformat(),
        "rule": {"weekly": rule["weekly"], "expiry_weekday": rule["expiry_weekday"],
                 "holiday_shift": "previous trading day"},
        "is_expiry_today": bool(nxt and nxt["expiry"] == today.isoformat()),
        "next_expiry": nxt,
        "expiries": items,
        "warnings": warnings,
    }

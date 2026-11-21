"""IST clock and market-session state. The ONE place that decides whether the market is open."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from . import resources

IST = ZoneInfo("Asia/Kolkata")

# NSE/BSE equity-derivatives timings (F&O has no pre-open call auction for options;
# the equity pre-open 09:00-09:15 still matters because index spot is discovered then).
PRE_OPEN_START = dt.time(9, 0)
MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)
EXPIRY_CUTOFF = dt.time(15, 30)


def now_ist() -> dt.datetime:
    return dt.datetime.now(tz=IST)


def to_ist(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def is_holiday(day: dt.date, exchange: str = "NSE") -> bool:
    return day in resources.holidays(exchange)


def holiday_name(day: dt.date, exchange: str = "NSE") -> str | None:
    return resources.holidays(exchange).get(day)


def holidays_verified(day: dt.date, exchange: str = "NSE") -> bool:
    """True only when the official holiday list for `day.year` is bundled."""
    return day.year in resources.holiday_years(exchange)


def is_trading_day(day: dt.date, exchange: str = "NSE") -> bool:
    return day.weekday() < 5 and not is_holiday(day, exchange)


def previous_trading_day(day: dt.date, exchange: str = "NSE") -> dt.date:
    d = day - dt.timedelta(days=1)
    while not is_trading_day(d, exchange):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(day: dt.date, exchange: str = "NSE") -> dt.date:
    d = day + dt.timedelta(days=1)
    while not is_trading_day(d, exchange):
        d += dt.timedelta(days=1)
    return d


def trading_days_between(start: dt.date, end: dt.date, exchange: str = "NSE") -> int:
    """Trading sessions in (start, end] - e.g. sessions left until expiry, counting expiry day."""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += dt.timedelta(days=1)
        if is_trading_day(d, exchange):
            n += 1
    return n


def market_state(ts: dt.datetime | None = None, exchange: str = "NSE") -> dict:
    """Return {'state': pre_open|open|closed|holiday|weekend, ...} for an IST timestamp."""
    ts = to_ist(ts or now_ist())
    day = ts.date()
    base = {"ts_ist": ts.isoformat(timespec="seconds"), "exchange": exchange,
            "holidays_verified": holidays_verified(day, exchange)}
    if day.weekday() >= 5:
        return {**base, "state": "weekend"}
    if is_holiday(day, exchange):
        return {**base, "state": "holiday", "holiday": holiday_name(day, exchange)}
    t = ts.time()
    if PRE_OPEN_START <= t < MARKET_OPEN:
        state = "pre_open"
    elif MARKET_OPEN <= t < MARKET_CLOSE:
        state = "open"
    else:
        state = "closed"
    return {**base, "state": state}

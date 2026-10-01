"""Date/time helpers.

Internally we use **timezone-aware** :class:`~datetime.datetime` values in
``Asia/Dhaka``. We deliberately avoid naive datetimes because they cause
subtle bugs around midnight and DST (Bangladesh does not observe DST, but
being explicit keeps arithmetic and comparisons unambiguous).
"""
from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Dhaka")

DATE_FMT = "%Y-%m-%d"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DISPLAY_DATE_FMT = "%d %b %Y"      # e.g. "01 Oct 2026"
DISPLAY_DATETIME_FMT = "%d %b %Y, %I:%M %p"


def now() -> _dt.datetime:
    """Current aware datetime in Asia/Dhaka."""
    return _dt.datetime.now(tz=TZ)


def local_now() -> _dt.datetime:
    """Current time as a *naive* datetime in Asia/Dhaka (for comparison to
    DB-stored naive local timestamps)."""
    return now().replace(tzinfo=None)


def start_of_day(d: _dt.datetime | _dt.date) -> _dt.datetime:
    """Midnight (00:00:00) naive local for the given date/datetime."""
    if isinstance(d, _dt.datetime):
        d = d.date()
    return _dt.datetime.combine(d, _dt.time(0, 0, 0))


def end_of_day(d: _dt.datetime | _dt.date) -> _dt.datetime:
    """23:59:59.999999 naive local for the given date/datetime."""
    if isinstance(d, _dt.datetime):
        d = d.date()
    return _dt.datetime.combine(d, _dt.time(23, 59, 59, 999999))


def today() -> _dt.date:
    return now().date()


def combine(d: _dt.date, t: _dt.time | None = None) -> _dt.datetime:
    if t is None:
        t = _dt.time(0, 0, 0)
    return _dt.datetime.combine(d, t, tzinfo=TZ)


def format_date(d: _dt.date | None) -> str:
    return d.strftime(DISPLAY_DATE_FMT) if d else ""


def format_datetime(dt: _dt.datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).strftime(DISPLAY_DATETIME_FMT)


def parse_date(text: str, fmt: str = DATE_FMT) -> _dt.date:
    return _dt.datetime.strptime(text.strip(), fmt).date()


def parse_datetime(text: str, fmt: str = DATETIME_FMT) -> _dt.datetime:
    dt = _dt.datetime.strptime(text.strip(), fmt)
    return dt.replace(tzinfo=TZ)


def age_from_dob(dob: _dt.date | None, as_of: _dt.date | None = None) -> int | None:
    if dob is None:
        return None
    as_of = as_of or today()
    years = as_of.year - dob.year
    if (as_of.month, as_of.day) < (dob.month, dob.day):
        years -= 1
    return years

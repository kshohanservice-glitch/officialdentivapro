import datetime as dt

from dentiva.core.dates import (
    age_from_dob,
    end_of_day,
    format_date,
    format_datetime,
    local_now,
    now,
    start_of_day,
    today,
)


def test_now_is_aware_dhaka():
    n = now()
    assert n.tzinfo is not None
    assert n.tzinfo.key == "Asia/Dhaka"


def test_today_matches_now_date():
    assert today() == now().date()


def test_age_from_dob():
    # On 2026-10-01 per env date, a DOB of 2000-05-15 should be 26.
    assert age_from_dob(dt.date(2000, 5, 15), as_of=dt.date(2026, 10, 1)) == 26
    # Birthday not yet reached in-year.
    assert age_from_dob(dt.date(2000, 12, 31), as_of=dt.date(2026, 10, 1)) == 25
    assert age_from_dob(None) is None


def test_format_strings_return_strings():
    assert isinstance(format_date(today()), str)
    assert isinstance(format_datetime(now()), str)


def test_local_now_is_naive_but_represents_dhaka():
    n = local_now()
    assert n.tzinfo is None
    # Should be within a minute of now() when stripped of tz.
    assert abs((n - now().replace(tzinfo=None)).total_seconds()) < 5


def test_start_of_day_and_end_of_day():
    d = dt.date(2026, 10, 1)
    s = start_of_day(d)
    e = end_of_day(d)
    assert s.hour == 0 and s.minute == 0 and s.second == 0
    assert e.hour == 23 and e.minute == 59 and e.second == 59
    assert s.date() == d and e.date() == d
    # Accept either datetime or date input.
    s2 = start_of_day(dt.datetime(2026, 10, 1, 14, 30))
    assert s2.hour == 0 and s2.date() == d

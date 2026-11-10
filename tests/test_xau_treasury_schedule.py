"""Contract tests for read-only Treasury session / FRED scheduling."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fx_scanner.xau_treasury_schedule import (
    fred_daily_release_key, holiday_name, is_treasury_session_day,
    next_h15_release, treasury_session_status,
)

WIB = ZoneInfo("Asia/Jakarta")
NY = ZoneInfo("America/New_York")


def test_veterans_day_2026_is_fixed_income_holiday():
    assert holiday_name(date(2026, 11, 11)) == "Veterans Day"
    assert not is_treasury_session_day(date(2026, 11, 11))
    assert treasury_session_status(datetime(2026, 11, 11, 16, 0, tzinfo=WIB))["status"] == "MARKET_HOLIDAY"


def test_wib_morning_is_still_previous_new_york_day():
    state = treasury_session_status(datetime(2026, 11, 11, 6, 16, tzinfo=WIB))
    assert state["ny_date"] == "2026-11-10"
    assert state["status"] == "PRE_HOLIDAY"
    assert state["holiday_tomorrow"] == "Veterans Day"


def test_daily_release_cache_never_advances_on_holiday():
    assert fred_daily_release_key(datetime(2026, 11, 10, 16, 44, tzinfo=NY)) == "2026-11-09"
    assert fred_daily_release_key(datetime(2026, 11, 10, 16, 46, tzinfo=NY)) == "2026-11-10"
    assert fred_daily_release_key(datetime(2026, 11, 11, 18, 0, tzinfo=NY)) == "2026-11-10"
    assert fred_daily_release_key(datetime(2026, 11, 12, 16, 44, tzinfo=NY)) == "2026-11-10"
    assert fred_daily_release_key(datetime(2026, 11, 12, 16, 46, tzinfo=NY)) == "2026-11-12"


def test_next_h15_release_skips_holiday_and_handles_wib_dst():
    nxt = next_h15_release(datetime(2026, 11, 11, 8, 0, tzinfo=NY))
    assert nxt.date() == date(2026, 11, 12)
    assert nxt.hour == 16 and nxt.minute == 15
    assert nxt.astimezone(WIB).strftime("%Y-%m-%d %H:%M") == "2026-11-13 04:15"


def test_sifma_2026_early_close_and_no_trade_day():
    assert treasury_session_status(datetime(2026, 4, 3, 13, 0, tzinfo=NY))["status"] == "EARLY_CLOSE"
    assert is_treasury_session_day(date(2026, 4, 3))
    assert not is_treasury_session_day(date(2026, 7, 3))

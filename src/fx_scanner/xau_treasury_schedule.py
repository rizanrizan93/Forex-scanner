"""Read-only U.S. Treasury trading-day and H.15 publication schedule.

Trading holidays follow the 2026 SIFMA fixed-income recommendations and a
conservative U.S. holiday-rule fallback for other years. This calendar is not a
live venue-status API; unscheduled closures need an operator override.
All scheduling uses America/New_York so WIB/DST conversion is automatic.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
WIB = ZoneInfo("Asia/Jakarta")
H15_RELEASE_ET = time(16, 15)
# Fetch the FRED mirror once after its upstream H.15 release, allowing a
# short publication buffer rather than a minute-by-minute dashboard poll.
FRED_FETCH_ET = time(16, 45)

_SIFMA_2026_HOLIDAYS = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 19): "Martin Luther King Jr. Day",
    date(2026, 2, 16): "Presidents Day",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day (observed)",
    date(2026, 9, 7): "Labor Day",
    date(2026, 10, 12): "Columbus Day",
    date(2026, 11, 11): "Veterans Day",
    date(2026, 11, 26): "Thanksgiving",
    date(2026, 12, 25): "Christmas Day",
}
_SIFMA_2026_EARLY_CLOSE_ET = {
    date(2026, 4, 3): time(12, 0),
    date(2026, 5, 22): time(14, 0),
    date(2026, 7, 2): time(14, 0),
    date(2026, 11, 27): time(14, 0),
    date(2026, 12, 24): time(14, 0),
    date(2026, 12, 31): time(14, 0),
}


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(holiday: date) -> date:
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _rule_holidays(year: int) -> dict[date, str]:
    fixed = [
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (date(year, 11, 11), "Veterans Day"),
        (date(year, 12, 25), "Christmas Day"),
    ]
    days = {_observed(day): name for day, name in fixed}
    days.update({
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Presidents Day",
        _last_weekday(year, 5, 0): "Memorial Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 10, 0, 2): "Columbus Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving",
    })
    return days


def holiday_name(day: date) -> str | None:
    if day.year == 2026:
        return _SIFMA_2026_HOLIDAYS.get(day)
    # The rule-based fallback is indicative, not a verified annual SIFMA
    # schedule. Extraordinary market closures are not detectable here.
    return _rule_holidays(day.year).get(day)


def is_treasury_session_day(day: date) -> bool:
    return day.weekday() < 5 and holiday_name(day) is None


def treasury_session_status(now: datetime | None = None) -> dict:
    """Calendar label only: does not certify quote or actual venue uptime."""
    now = now or datetime.now(NY)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    local = now.astimezone(NY)
    day = local.date()
    holiday = holiday_name(day)
    if holiday:
        code, label = "MARKET_HOLIDAY", holiday
    elif day.weekday() >= 5:
        code, label = "WEEKEND_CLOSED", "Weekend"
    elif day in _SIFMA_2026_EARLY_CLOSE_ET and local.time() >= _SIFMA_2026_EARLY_CLOSE_ET[day]:
        code, label = "EARLY_CLOSE", "SIFMA early close"
    elif holiday_name(day + timedelta(days=1)) and local.time() >= time(16, 0):
        code, label = "PRE_HOLIDAY", holiday_name(day + timedelta(days=1))
    else:
        code, label = "SCHEDULED_SESSION", "Regular trading day"
    return {
        "status": code,
        "label": label,
        "ny_date": day.isoformat(),
        "ny_time": local.strftime("%Y-%m-%d %H:%M %Z"),
        "holiday_tomorrow": holiday_name(day + timedelta(days=1)),
        "calendar_basis": "SIFMA_2026" if day.year == 2026 else "RULE_BASED_UNVERIFIED",
    }


def _last_release_day(now: datetime, *, fetch_time: time) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    local = now.astimezone(NY)
    day = local.date()
    if local.time() < fetch_time or not is_treasury_session_day(day):
        day -= timedelta(days=1)
    for _ in range(15):
        if is_treasury_session_day(day):
            return day
        day -= timedelta(days=1)
    raise ValueError("No valid H.15 release day within 15 days")


def fred_daily_release_key(now: datetime | None = None) -> str:
    """Stable key between releases: no HTTP re-fetch on 15-second UI reruns."""
    return _last_release_day(now or datetime.now(NY), fetch_time=FRED_FETCH_ET).isoformat()


def next_h15_release(now: datetime | None = None) -> datetime:
    now = now or datetime.now(NY)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    local = now.astimezone(NY)
    day = local.date()
    for _ in range(15):
        if is_treasury_session_day(day):
            candidate = datetime.combine(day, H15_RELEASE_ET, tzinfo=NY)
            if candidate > local:
                return candidate
        day += timedelta(days=1)
    raise ValueError("No upcoming H.15 release within 15 days")

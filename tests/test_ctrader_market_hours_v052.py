from datetime import datetime, timezone
from types import SimpleNamespace

from fx_scanner.execution.ctrader_market_hours import evaluate_ctrader_market_status

UTC = timezone.utc


def _symbol(*, start: int, end: int, mode: int = 0, tz: str = "UTC", holidays=()):
    return SimpleNamespace(
        tradingMode=mode,
        scheduleTimeZone=tz,
        schedule=(SimpleNamespace(startSecond=start, endSecond=end),),
        holiday=tuple(holidays),
        digits=5,
        pipPosition=4,
    )


def test_broker_schedule_is_authoritative_open_inside_interval():
    # Saturday 12:00 UTC = 6 days + 12h after Sunday 00:00.
    second = 6 * 86400 + 12 * 3600
    info = _symbol(start=second - 60, end=second + 60)

    status = evaluate_ctrader_market_status(
        info,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    assert status.open_for_new_positions is True
    assert status.reason == "OPEN"
    assert status.broker_pip_size == 0.0001
    assert status.digits == 5


def test_broker_schedule_fails_closed_outside_interval():
    info = _symbol(start=0, end=5 * 86400)

    status = evaluate_ctrader_market_status(
        info,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    assert status.open_for_new_positions is False
    assert status.reason == "OUTSIDE_BROKER_SESSION"


def test_trading_mode_blocks_even_when_schedule_open():
    info = _symbol(start=0, end=7 * 86400, mode=3)

    status = evaluate_ctrader_market_status(
        info,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    assert status.open_for_new_positions is False
    assert status.reason == "TRADING_MODE_3"


def test_missing_or_unknown_timezone_fails_closed():
    missing = _symbol(start=0, end=7 * 86400, tz="")
    unknown = _symbol(start=0, end=7 * 86400, tz="NOT/A_REAL_ZONE")

    missing_status = evaluate_ctrader_market_status(
        missing,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )
    unknown_status = evaluate_ctrader_market_status(
        unknown,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    assert missing_status.open_for_new_positions is False
    assert missing_status.reason == "SCHEDULE_TIMEZONE_MISSING"
    assert unknown_status.open_for_new_positions is False
    assert unknown_status.reason.startswith("SCHEDULE_TIMEZONE_UNSUPPORTED:")


def test_full_day_broker_holiday_blocks_entry():
    holiday_days = (
        datetime(2026, 9, 5, tzinfo=UTC).date()
        - datetime(1970, 1, 1, tzinfo=UTC).date()
    ).days
    holiday = SimpleNamespace(
        scheduleTimeZone="UTC",
        holidayDate=holiday_days,
        isRecurring=False,
    )
    info = _symbol(start=0, end=7 * 86400, holidays=(holiday,))

    status = evaluate_ctrader_market_status(
        info,
        at=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
    )

    assert status.open_for_new_positions is False
    assert status.reason == "BROKER_HOLIDAY"

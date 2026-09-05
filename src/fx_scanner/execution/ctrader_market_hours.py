from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
_SECONDS_PER_DAY = 86_400
_SECONDS_PER_WEEK = 7 * _SECONDS_PER_DAY


@dataclass(frozen=True, slots=True)
class CTraderMarketStatus:
    open_for_new_positions: bool
    reason: str
    trading_mode: int
    schedule_timezone: str
    week_second: int | None
    configured_intervals: int
    broker_pip_size: float | None
    digits: int | None


def _resolve_timezone(name: str):
    value = str(name or "").strip()
    if value in {"UTC", "Etc/UTC", "GMT", "Etc/GMT"}:
        return UTC
    if not value:
        raise ValueError("SCHEDULE_TIMEZONE_MISSING")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"SCHEDULE_TIMEZONE_UNSUPPORTED:{value}") from exc


def _week_second(local_now: datetime) -> int:
    # Python weekday(): Monday=0. cTrader schedule: Sunday=0.
    sunday_index = (local_now.weekday() + 1) % 7
    return (
        sunday_index * _SECONDS_PER_DAY
        + local_now.hour * 3600
        + local_now.minute * 60
        + local_now.second
    )


def _field_present(message, name: str) -> bool:
    try:
        return bool(message.HasField(name))
    except Exception:
        return hasattr(message, name)


def _holiday_blocks(holiday, *, at: datetime) -> bool:
    timezone_name = str(getattr(holiday, "scheduleTimeZone", "") or "").strip()
    try:
        tz = _resolve_timezone(timezone_name)
    except ValueError:
        # Unknown holiday timezone is not safe to ignore.
        return True
    local_now = at.astimezone(tz)
    raw_days = int(getattr(holiday, "holidayDate", 0) or 0)
    holiday_date = date(1970, 1, 1) + timedelta(days=raw_days)
    recurring = bool(getattr(holiday, "isRecurring", False))
    date_matches = (
        (local_now.month, local_now.day) == (holiday_date.month, holiday_date.day)
        if recurring
        else local_now.date() == holiday_date
    )
    if not date_matches:
        return False

    has_start = _field_present(holiday, "startSecond")
    has_end = _field_present(holiday, "endSecond")
    if not has_start and not has_end:
        return True
    start = int(getattr(holiday, "startSecond", 0) or 0)
    end = int(getattr(holiday, "endSecond", 0) or 0)
    if not has_end or end <= start:
        end = _SECONDS_PER_DAY
    second = local_now.hour * 3600 + local_now.minute * 60 + local_now.second
    return start <= second < end


def evaluate_ctrader_market_status(symbol_info, *, at: datetime | None = None) -> CTraderMarketStatus:
    """Evaluate whether cTrader permits a new position for one symbol.

    The broker's ProtoOASymbol tradingMode, schedule/scheduleTimeZone and holiday
    fields are authoritative. Missing or unsupported schedule metadata fails
    closed. This only answers market availability; all existing trading guards
    remain independent and still apply after this gate.
    """
    current = at or datetime.now(tz=UTC)
    if current.tzinfo is None:
        raise ValueError("market-status clock must be timezone-aware")
    current = current.astimezone(UTC)

    trading_mode = int(getattr(symbol_info, "tradingMode", 0) or 0)
    timezone_name = str(getattr(symbol_info, "scheduleTimeZone", "") or "").strip()
    schedule = tuple(getattr(symbol_info, "schedule", ()) or ())
    digits = int(getattr(symbol_info, "digits", 0) or 0)
    pip_position = int(getattr(symbol_info, "pipPosition", 0) or 0)
    broker_pip_size = 10.0 ** (-pip_position) if pip_position > 0 else None

    if trading_mode != 0:
        return CTraderMarketStatus(
            False,
            f"TRADING_MODE_{trading_mode}",
            trading_mode,
            timezone_name,
            None,
            len(schedule),
            broker_pip_size,
            digits or None,
        )

    try:
        tz = _resolve_timezone(timezone_name)
    except ValueError as exc:
        return CTraderMarketStatus(
            False,
            str(exc),
            trading_mode,
            timezone_name,
            None,
            len(schedule),
            broker_pip_size,
            digits or None,
        )

    if not schedule:
        return CTraderMarketStatus(
            False,
            "SCHEDULE_EMPTY",
            trading_mode,
            timezone_name,
            None,
            0,
            broker_pip_size,
            digits or None,
        )

    for holiday in tuple(getattr(symbol_info, "holiday", ()) or ()):
        if _holiday_blocks(holiday, at=current):
            return CTraderMarketStatus(
                False,
                "BROKER_HOLIDAY",
                trading_mode,
                timezone_name,
                _week_second(current.astimezone(tz)),
                len(schedule),
                broker_pip_size,
                digits or None,
            )

    week_second = _week_second(current.astimezone(tz))
    open_now = any(
        int(getattr(interval, "startSecond", 0) or 0)
        <= week_second
        < int(getattr(interval, "endSecond", 0) or 0)
        for interval in schedule
    )
    return CTraderMarketStatus(
        open_now,
        "OPEN" if open_now else "OUTSIDE_BROKER_SESSION",
        trading_mode,
        timezone_name,
        week_second,
        len(schedule),
        broker_pip_size,
        digits or None,
    )

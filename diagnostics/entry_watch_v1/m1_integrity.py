"""Read-only quality checks for native cTrader M1 broker trendbars.

A missing trendbar may be a legitimate no-tick minute or a broker/API data gap.
This module never synthesizes OHLC or changes the frozen trading strategy.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
WIB = ZoneInfo('Asia/Jakarta')
MINUTE = timedelta(minutes=1)


def _schedule(contract):
    zone = ZoneInfo(contract['scheduleTimeZone'])
    periods = tuple((int(x['startSecond']), int(x['endSecond']))
                    for x in contract['schedule'])
    if not periods or any(a < 0 or a >= b or b > 604800 for a, b in periods):
        raise ValueError('INVALID_BROKER_TRADING_SCHEDULE')
    return zone, periods


def market_open(at_utc, contract):
    """Broker trading schedule uses seconds since Sunday 00:00 local time."""
    zone, periods = _schedule(contract)
    local = at_utc.astimezone(zone)
    second = ((local.weekday() + 1) % 7) * 86400 + (local.hour * 3600 + local.minute * 60)
    return any(begin <= second < end for begin, end in periods)


def in_frozen_entry_session(symbol, at_utc):
    local = at_utc.astimezone(WIB)
    if symbol == 'XAUUSD':
        return 19 <= local.hour < 24
    if symbol == 'EURUSD':
        return 14 <= local.hour < 19
    if symbol == 'BTCUSD':
        return True  # still subject to the separate BTC weekend guard
    return False


def inspect(symbol, timestamps, contract, max_ranges=30):
    """Classify absent native M1 timestamps between first and last observed bars.

    No complete-bar assertion is made about the leading/trailing minute of the
    requested range. Missing values never become fabricated OHLC candles.
    """
    moments = sorted(set(timestamps))
    if not moments:
        return {'status': 'NO_BROKER_BARS', 'open_missing': 0,
                'closed_missing': 0, 'strategy_missing': 0,
                'open_missing_minutes': [], 'ranges': []}
    if any(t.tzinfo is None or t.second != 0 or t.microsecond for t in moments):
        raise ValueError('INVALID_M1_TIMESTAMP_ALIGNMENT')
    if any(t.utcoffset() != timedelta(0) for t in moments):
        raise ValueError('M1_TIMESTAMPS_MUST_BE_UTC')
    zone, periods = _schedule(contract)
    open_missing, closed_missing, strategy_missing = [], [], []
    ranges = []
    for prev, nxt in zip(moments, moments[1:]):
        delta = nxt - prev
        if delta < MINUTE or delta % MINUTE:
            raise ValueError('INVALID_M1_CADENCE')
        missing_count = int(delta / MINUTE) - 1
        if not missing_count:
            continue
        for idx in range(1, missing_count + 1):
            missing = prev + idx * MINUTE
            local = missing.astimezone(zone)
            second = ((local.weekday() + 1) % 7) * 86400 + local.hour * 3600 + local.minute * 60
            is_open = any(begin <= second < end for begin, end in periods)
            if is_open:
                open_missing.append(missing)
                if in_frozen_entry_session(symbol, missing):
                    strategy_missing.append(missing)
            else:
                closed_missing.append(missing)
    if open_missing:
        begin = last = open_missing[0]
        for moment in open_missing[1:]:
            if moment == last + MINUTE:
                last = moment
            else:
                ranges.append({'first_utc': begin.isoformat(), 'last_utc': last.isoformat(),
                               'minutes': int((last - begin) / MINUTE) + 1})
                begin = last = moment
        ranges.append({'first_utc': begin.isoformat(), 'last_utc': last.isoformat(),
                       'minutes': int((last - begin) / MINUTE) + 1})
    return {
        'status': ('STRATEGY_SESSION_M1_UNRESOLVED' if strategy_missing else
                   'OUTSIDE_STRATEGY_SESSION_M1_UNRESOLVED' if open_missing else
                   'SCHEDULE_ACCOUNTED'),
        'bars': len(moments), 'first_utc': moments[0].isoformat(),
        'last_utc': moments[-1].isoformat(),
        'open_missing': len(open_missing),
        'closed_missing': len(closed_missing),
        'strategy_missing': len(strategy_missing),
        'open_missing_minutes': open_missing,
        'ranges': ranges[:max_ranges], 'range_count': len(ranges),
        'ranges_truncated': len(ranges) > max_ranges,
        'interpolation_used': False,
        'interpretation': 'NO_TICK_OR_MISSING_BROKER_BAR_UNRESOLVED',
    }


def retry_windows(open_missing_minutes, max_days=21, pad_minutes=20):
    """Bounded one-read-per-UTC-day plans for missing market-open minutes."""
    grouped = defaultdict(list)
    for at in open_missing_minutes:
        grouped[at.date()].append(at)
    windows = []
    for day in sorted(grouped)[:max_days]:
        points = sorted(grouped[day])
        start = max(datetime(day.year, day.month, day.day, tzinfo=UTC),
                    points[0] - timedelta(minutes=pad_minutes))
        finish = min(start.replace(hour=0, minute=0) + timedelta(days=1),
                     points[-1] + timedelta(minutes=pad_minutes + 1))
        if finish <= start:
            raise AssertionError('EMPTY_BACKFILL_RANGE')
        windows.append((start, finish))
    return windows


def public_report(result):
    """Report safe JSON scalars; internal datetime array is for retries only."""
    return {key: value for key, value in result.items() if key != 'open_missing_minutes'}

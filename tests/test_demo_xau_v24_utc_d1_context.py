from datetime import date, datetime, timedelta, timezone

import pytest

from fx_scanner.demo_xau_v24_utc_d1_context import (
    DailyOhlc,
    UtcD1Context,
    _parse_context,
    advance_context,
    aggregate_h1_to_utc_days,
    context_from_daily,
)
from fx_scanner.models import Bar

UTC = timezone.utc


def _h1(day: date, hour: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="H1",
        timestamp=datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        + timedelta(hours=hour),
        open=o,
        high=h,
        low=l,
        close=c,
        tick_count=100,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_h1_aggregation_reconstructs_utc_calendar_day():
    day = date(2026, 9, 21)
    rows = (
        _h1(day, 0, 100, 103, 99, 102),
        _h1(day, 1, 102, 105, 101, 104),
        _h1(day, 23, 104, 108, 103, 107),
    )
    daily = aggregate_h1_to_utc_days(rows, before_day=day + timedelta(days=1))
    assert daily == (
        DailyOhlc(day=day, open=100.0, high=108.0, low=99.0, close=107.0),
    )


def _daily_history(count: int = 260) -> tuple[DailyOhlc, ...]:
    start = date(2025, 1, 1)
    rows = []
    for i in range(count):
        base = 2000.0 + i * 2.0
        rows.append(
            DailyOhlc(
                day=start + timedelta(days=i),
                open=base,
                high=base + 10.0,
                low=base - 10.0,
                close=base + 4.0,
            )
        )
    return tuple(rows)


def test_full_context_and_incremental_context_follow_same_ewm_recurrence():
    history = _daily_history(260)
    split_target = history[240].day
    prior = context_from_daily(history[:240], target_day=split_target)
    target_day = history[-1].day + timedelta(days=1)
    incremental = advance_context(
        prior,
        history[240:],
        target_day=target_day,
    )
    full = context_from_daily(history, target_day=target_day)

    assert incremental.signal_day == full.signal_day
    assert incremental.direction == full.direction
    assert incremental.atr14 == pytest.approx(full.atr14, rel=0, abs=1e-12)
    assert incremental.ema200 == pytest.approx(full.ema200, rel=0, abs=1e-12)
    assert incremental.ret60 == pytest.approx(full.ret60, rel=0, abs=1e-12)
    assert incremental.close == pytest.approx(full.close, rel=0, abs=1e-12)
    assert incremental.closes_tail == pytest.approx(full.closes_tail)


def test_cached_context_payload_roundtrips_and_keeps_last_61_closes():
    history = _daily_history(260)
    target_day = history[-1].day + timedelta(days=1)
    context = context_from_daily(history, target_day=target_day)
    parsed = _parse_context(context.payload())
    assert parsed is not None
    assert parsed.target_day == context.target_day
    assert parsed.signal_day == context.signal_day
    assert parsed.direction == context.direction
    assert parsed.atr14 == pytest.approx(context.atr14)
    assert parsed.ema200 == pytest.approx(context.ema200)
    assert len(parsed.closes_tail) == 61


def test_carry_forward_does_not_invent_a_daily_bar_when_market_was_closed():
    history = _daily_history(240)
    prior = context_from_daily(
        history,
        target_day=history[-1].day + timedelta(days=1),
    )
    target_day = prior.target_day + timedelta(days=1)
    carried = advance_context(prior, (), target_day=target_day)
    assert carried.target_day == target_day
    assert carried.signal_day == prior.signal_day
    assert carried.direction == prior.direction
    assert carried.atr14 == prior.atr14
    assert carried.ema200 == prior.ema200
    assert carried.source == "CACHE_CARRY_FORWARD"

from datetime import date, datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_d1_tsmom_crossfeed_v1 import (
    DailyBar,
    Summary,
    Trade,
    _ema,
    _wilder_atr,
    crossfeed_pass,
    resample_h1_to_daily,
    summarize,
)

UTC = timezone.utc


def _bar(stamp: datetime, price: float) -> Bar:
    return Bar(
        symbol="XAUUSD",
        timeframe="H1",
        timestamp=stamp,
        open=price,
        high=price + 1.0,
        low=price - 1.0,
        close=price + 0.25,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def test_adjust_false_ema_matches_recursive_seed_contract():
    values = [1.0, 2.0, 3.0, 4.0]
    result = _ema(values, 3)
    assert result[:2] == [None, None]
    assert result[2] == 2.25
    assert result[3] == 3.125


def test_wilder_atr_uses_adjust_false_recursive_seed():
    rows = tuple(
        DailyBar(date(2026, 1, 1) + timedelta(days=i), 100.0, 102.0, 99.0, 101.0)
        for i in range(4)
    )
    result = _wilder_atr(rows, period=3)
    assert result[:2] == [None, None]
    assert result[2] == 3.0
    assert result[3] == 3.0


def test_h1_resample_keeps_only_full_enough_broker_days():
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    complete = tuple(_bar(start + timedelta(hours=i), 2000.0 + i) for i in range(24))
    partial_start = start + timedelta(days=1)
    partial = tuple(_bar(partial_start + timedelta(hours=i), 2100.0 + i) for i in range(10))
    daily = resample_h1_to_daily(complete + partial, boundary_hour_utc=0)
    assert len(daily) == 1
    assert daily[0].day == start.date()


def test_stress_cost_repricing_cannot_improve_summary():
    trades = tuple(
        Trade(
            signal_day=date(2026, 1, i),
            entry_day=date(2026, 1, i + 1),
            exit_day=date(2026, 1, i + 1),
            direction=1,
            entry=2000.0,
            stop=1980.0,
            target=2040.0,
            risk_price=20.0,
            gross_r=1.0 if i % 2 else -0.2,
            exit_reason="TIME",
        )
        for i in range(1, 11)
    )
    base = summarize(trades, cost_usd=0.17)
    stress = summarize(trades, cost_usd=0.35)
    assert stress.expectancy_r < base.expectancy_r
    assert stress.net_r < base.net_r


def test_crossfeed_gate_requires_primary_quality_and_boundary_stability():
    good = Summary(30, 6.0, 0.20, 1.30, 0.55, 8.0, 0.85)
    weak = Summary(30, -1.0, -0.03, 0.90, 0.40, 9.0, 0.30)
    assert crossfeed_pass(good, (good, good, weak)) is True
    assert crossfeed_pass(good, (good, weak, weak)) is False

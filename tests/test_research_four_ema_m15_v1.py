from datetime import date, datetime, timedelta, timezone

import pytest

from fx_scanner.demo_four_ema import FOUR_EMA_PERIODS, build_four_ema_features
from fx_scanner.models import Bar
from fx_scanner.research_four_ema_m15_v1 import (
    FROZEN_CANDIDATES,
    FourEMATrade,
    _frame_state,
    _resample_h1,
    build_feature_cache,
    pip_size,
    reprice_cost,
    split_calendar,
    summarize,
)

UTC = timezone.utc


def _m15_rows(count: int = 8):
    start = datetime(2026, 1, 5, tzinfo=UTC)
    rows = []
    for index in range(count):
        price = 1.10 + index * 0.0001
        rows.append(
            Bar(
                symbol="EURUSD",
                timeframe="M15",
                timestamp=start + timedelta(minutes=15 * index),
                open=price,
                high=price + 0.0002,
                low=price - 0.0002,
                close=price + 0.0001,
                tick_count=10,
                spread_avg=0.0001,
                spread_max=0.0002,
            )
        )
    return tuple(rows)


def _trade(day: date, result: float) -> FourEMATrade:
    stamp = datetime(day.year, day.month, day.day, 8, tzinfo=UTC)
    return FourEMATrade(
        symbol="EURUSD",
        candidate=FROZEN_CANDIDATES[0].name,
        direction="LONG",
        decision_time=stamp,
        entry_time=stamp + timedelta(minutes=15),
        exit_time=stamp + timedelta(hours=1),
        entry_price=1.1000,
        stop_loss=1.0990,
        take_profit=1.1020,
        gross_r=result,
        net_r=result,
        exit_reason="TARGET" if result > 0 else "STOP",
    )


def test_frozen_candidates_and_period_geometry_are_fixed():
    assert [row.name for row in FROZEN_CANDIDATES] == [
        "FOUR_EMA_M15_2R",
        "FOUR_EMA_M15_2P5R",
        "FOUR_EMA_M15_LIQUID_2R",
    ]
    assert [row.target_r for row in FROZEN_CANDIDATES] == [2.0, 2.5, 2.0]


def test_resample_h1_uses_only_complete_four_bar_hours():
    rows = _m15_rows(8)
    h1 = _resample_h1(rows)
    assert len(h1) == 2
    assert h1[0].open == rows[0].open
    assert h1[0].close == rows[3].close
    assert h1[1].timestamp.hour == 1


def test_cached_direction_inference_matches_original_feature_contract():
    window = _m15_rows(120)
    state = _frame_state(window)
    long_features = build_four_ema_features(
        window,
        direction="LONG",
        periods=FOUR_EMA_PERIODS,
    )
    short_features = build_four_ema_features(
        window,
        direction="SHORT",
        periods=FOUR_EMA_PERIODS,
    )

    assert state.available is long_features.available is short_features.available
    assert state.alignment == long_features.alignment == short_features.alignment
    assert state.pullback == long_features.pullback_near_fast_cluster
    assert state.pullback == short_features.pullback_near_fast_cluster
    assert state.long_slopes == long_features.directional_slopes
    assert state.short_slopes == short_features.directional_slopes
    assert state.long_price_side == long_features.price_side_slow_ok
    assert state.short_price_side == short_features.price_side_slow_ok
    assert state.spread_state == long_features.spread_state == short_features.spread_state


def test_feature_cache_is_built_for_mature_decision_bars():
    rows = _m15_rows(300)
    cache = build_feature_cache(rows)
    assert cache
    assert min(cache) >= 220  # 55 complete H1 bars are required.
    for m15_state, h1_state in cache.values():
        assert isinstance(m15_state.available, bool)
        assert isinstance(h1_state.available, bool)


def test_pair_aware_pip_size():
    assert pip_size("EURUSD") == pytest.approx(0.0001)
    assert pip_size("USDJPY") == pytest.approx(0.01)


def test_cost_repricing_preserves_geometry_and_reduces_net_r():
    trade = _trade(date(2026, 1, 5), 2.0)
    priced = reprice_cost((trade,), round_trip_cost_pips=1.5)
    assert priced[0].entry_price == trade.entry_price
    assert priced[0].stop_loss == trade.stop_loss
    assert priced[0].gross_r == trade.gross_r
    assert priced[0].net_r < trade.gross_r


def test_calendar_split_is_explicit_and_summary_uses_net_r():
    rows = (
        _trade(date(2024, 6, 1), 2.0),
        _trade(date(2025, 6, 1), -1.0),
        _trade(date(2026, 6, 1), 2.0),
    )
    split = split_calendar(
        rows,
        train_end=date(2024, 12, 31),
        validation_end=date(2025, 12, 31),
        oos_end=date(2026, 8, 31),
    )
    assert {key: len(value) for key, value in split.items()} == {
        "train": 1,
        "validation": 1,
        "oos": 1,
    }
    assert summarize(rows).expectancy_r == pytest.approx(1.0)

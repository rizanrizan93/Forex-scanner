from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.demo_donchian_atr_h1 import build_donchian_atr_h1_features
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(index: int, *, close: float | None = None, high: float | None = None, low: float | None = None) -> Bar:
    base = 1.1000 + 0.00005 * index
    open_price = base
    close_price = base + 0.0001 if close is None else close
    high_price = max(open_price, close_price) + 0.0004 if high is None else high
    low_price = min(open_price, close_price) - 0.0004 if low is None else low
    return Bar(
        symbol="EURUSD",
        timeframe="H1",
        timestamp=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(hours=index),
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        tick_count=100 + index,
        spread_avg=0.0001,
        spread_max=0.0002,
    )


def _prior(count: int = 24) -> list[Bar]:
    return [_bar(index) for index in range(count)]


def test_donchian_h1_is_unavailable_with_insufficient_history():
    features = build_donchian_atr_h1_features(tuple(_prior(10)), direction="LONG")

    assert features.available is False
    assert features.breakout_triggered is False
    assert features.policy_effect == "OBSERVATION_ONLY"


def test_long_breakout_excludes_current_bar_from_channel_and_requires_atr_buffer():
    rows = _prior(24)
    prior_upper = max(row.high for row in rows[-20:])
    current = _bar(24, close=prior_upper + 0.0030, high=prior_upper + 0.0035)
    features = build_donchian_atr_h1_features(tuple(rows + [current]), direction="LONG")

    assert features.available is True
    assert features.channel_upper == pytest.approx(prior_upper)
    assert features.channel_upper < current.high
    assert features.close_beyond_channel is True
    assert features.intrabar_beyond_channel is True
    assert features.breakout_triggered is True
    assert features.breakout_distance_atr is not None
    assert features.breakout_distance_atr >= features.breakout_buffer_atr


def test_intrabar_wick_without_close_is_not_a_breakout_trigger():
    rows = _prior(24)
    prior_upper = max(row.high for row in rows[-20:])
    current = _bar(
        24,
        close=prior_upper - 0.0002,
        high=prior_upper + 0.0015,
        low=prior_upper - 0.0010,
    )
    features = build_donchian_atr_h1_features(tuple(rows + [current]), direction="LONG")

    assert features.available is True
    assert features.intrabar_beyond_channel is True
    assert features.close_beyond_channel is False
    assert features.breakout_triggered is False


def test_short_breakout_uses_prior_lower_channel_and_atr_buffer():
    rows = _prior(24)
    prior_lower = min(row.low for row in rows[-20:])
    current = _bar(
        24,
        close=prior_lower - 0.0030,
        low=prior_lower - 0.0035,
    )
    features = build_donchian_atr_h1_features(tuple(rows + [current]), direction="SHORT")

    assert features.available is True
    assert features.channel_lower == pytest.approx(prior_lower)
    assert features.close_beyond_channel is True
    assert features.breakout_triggered is True
    assert features.breakout_distance_atr is not None
    assert features.breakout_distance_atr >= features.breakout_buffer_atr


def test_invalid_direction_and_negative_buffer_fail_closed():
    rows = tuple(_prior(25))
    with pytest.raises(ValueError):
        build_donchian_atr_h1_features(rows, direction="FLAT")
    with pytest.raises(ValueError):
        build_donchian_atr_h1_features(rows, direction="LONG", breakout_buffer_atr=-0.1)

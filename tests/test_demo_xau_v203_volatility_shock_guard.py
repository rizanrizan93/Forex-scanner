from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_v203_volatility_shock_guard import (
    evaluate_volatility_shock_guard,
)
from fx_scanner.models import Bar


START = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


def _bar(
    index: int,
    *,
    open_=100.0,
    high=101.0,
    low=99.0,
    close=100.5,
    tick_count=100,
    spread_avg=0.20,
    spread_max=0.30,
):
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=START + timedelta(minutes=5 * index),
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        tick_count=int(tick_count),
        spread_avg=float(spread_avg),
        spread_max=float(spread_max),
    )


def _baseline(count=48):
    return tuple(_bar(i) for i in range(count))


def _as_of(bars, *, extra_minutes=5):
    return bars[-1].timestamp + timedelta(minutes=extra_minutes)


def test_v203_normal_market_has_no_shadow_block():
    bars = _baseline() + (_bar(48),)
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    assert out["state"] == "NORMAL"
    assert out["shadow_action"] == "NO_SHADOW_BLOCK"
    assert out["shadow_aggressive_entry_block_recommended"] is False
    assert out["recommended_micro_authority_multiplier"] == 1.0
    assert out["effective_execution_block"] is False
    assert out["execution_authority"] is False
    assert out["direction_engine_influence"] is False


def test_v203_abnormal_range_expansion_is_shock():
    bars = _baseline() + (
        _bar(
            48,
            open_=100.0,
            high=106.0,
            low=94.0,
            close=105.0,
            tick_count=120,
        ),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    latest = out["latest_completed_m5"]
    assert out["state"] == "SHOCK"
    assert "ABNORMAL_RANGE_EXPANSION" in latest["shock_reasons"]
    assert latest["range_ratio"] == 6.0
    assert out["shadow_action"] == "OBSERVE_ONLY"
    assert out["recommended_micro_authority_multiplier"] == 0.0
    assert out["effective_execution_block"] is False


def test_v203_spread_expansion_is_shock_when_spread_data_available():
    bars = _baseline() + (
        _bar(
            48,
            spread_avg=0.80,
            spread_max=1.00,
        ),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    latest = out["latest_completed_m5"]
    assert out["state"] == "SHOCK"
    assert "SPREAD_SHOCK" in latest["shock_reasons"]
    assert latest["spread_ratio"] > 3.0
    assert out["data_quality"]["spread_signal_available"] is True


def test_v203_liquidity_vacuum_proxy_requires_large_directional_range_and_low_ticks():
    bars = _baseline() + (
        _bar(
            48,
            open_=100.0,
            high=103.5,
            low=99.5,
            close=103.0,
            tick_count=40,
        ),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    latest = out["latest_completed_m5"]
    assert out["state"] == "SHOCK"
    assert latest["range_ratio"] == 2.0
    assert latest["tick_ratio"] == 0.4
    assert latest["body_fraction"] >= 0.65
    assert "LIQUIDITY_VACUUM_PROXY" in latest["shock_reasons"]
    assert out["data_quality"]["liquidity_vacuum_is_proxy_not_dom_depth"] is True


def test_v203_recent_shock_enters_stabilizing_before_three_stable_bars():
    bars = _baseline() + (
        _bar(
            48,
            open_=100.0,
            high=106.0,
            low=94.0,
            close=105.0,
        ),
        _bar(49),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    assert out["state"] == "STABILIZING"
    assert out["stable_completed_m5_run"] == 1
    assert out["shadow_action"] == "PREPARE_ONLY"
    assert out["recommended_micro_authority_multiplier"] == 0.25
    assert out["shadow_aggressive_entry_block_recommended"] is True


def test_v203_returns_normal_after_three_stable_completed_m5_bars():
    bars = _baseline() + (
        _bar(
            48,
            open_=100.0,
            high=106.0,
            low=94.0,
            close=105.0,
        ),
        _bar(49),
        _bar(50),
        _bar(51),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    assert out["stable_completed_m5_run"] >= 3
    assert out["state"] == "NORMAL"
    assert out["shadow_aggressive_entry_block_recommended"] is False


def test_v203_unfinished_m5_shock_is_excluded():
    bars = _baseline() + (
        _bar(48),
        _bar(
            49,
            open_=100.0,
            high=110.0,
            low=90.0,
            close=109.0,
            spread_avg=1.0,
            spread_max=1.2,
        ),
    )
    # Bar 49 opened at 14:05 UTC and is not closed yet at 14:08.
    out = evaluate_volatility_shock_guard(
        bars,
        as_of=bars[-1].timestamp + timedelta(minutes=3),
    )
    assert out["latest_completed_m5"]["bar_at"] == bars[-2].timestamp.isoformat()
    assert out["state"] == "NORMAL"
    assert out["data_quality"]["current_unfinished_m5_excluded"] is True


def test_v203_insufficient_data_fails_closed_in_shadow_only_mode():
    bars = tuple(_bar(i) for i in range(20))
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    assert out["state"] == "INSUFFICIENT_DATA"
    assert out["shadow_action"] == "OBSERVE_ONLY"
    assert out["shadow_aggressive_entry_block_recommended"] is True
    assert out["recommended_micro_authority_multiplier"] == 0.0
    assert out["effective_execution_block"] is False
    assert out["execution_authority"] is False


def test_v203_zero_spread_history_disables_spread_signal_without_failure():
    bars = tuple(
        _bar(i, spread_avg=0.0, spread_max=0.0)
        for i in range(48)
    ) + (
        _bar(48, spread_avg=0.0, spread_max=0.0),
    )
    out = evaluate_volatility_shock_guard(bars, as_of=_as_of(bars))
    assert out["state"] == "NORMAL"
    assert out["latest_completed_m5"]["spread_ratio"] is None
    assert out["data_quality"]["spread_signal_available"] is False

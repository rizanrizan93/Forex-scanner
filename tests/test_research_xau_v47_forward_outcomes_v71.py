from datetime import datetime, timedelta, timezone

from fx_scanner.models import Bar
from fx_scanner.research_xau_v47_forward_outcomes_v71 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MAX_HOLD_BARS,
    OUTCOME_EVENT,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    resolve_forward_outcome,
    summarize_outcomes,
)

UTC = timezone.utc


def _bar(index, *, low=99.5, high=100.5, close=100.0):
    return Bar(
        symbol="XAUUSD",
        timeframe="M15",
        timestamp=datetime(2026, 9, 21, tzinfo=UTC) + timedelta(minutes=15 * index),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


def _evaluation(**overrides):
    payload = {
        "direction": "LONG",
        "entry_at": datetime(2026, 9, 21, tzinfo=UTC).isoformat(),
        "entry_price": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "reward_r": 2.0,
        "entry_friction_r": 0.10,
    }
    payload.update(overrides)
    return payload


def test_v71_is_outcome_only_shadow_contract():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert OUTCOME_EVENT == "DEMO_XAU_V47_FORWARD_OUTCOME"


def test_v71_stop_first_on_ambiguous_entry_bar():
    bars = (_bar(0, low=98.5, high=102.5),)
    result = resolve_forward_outcome(bars, evaluation=_evaluation())
    assert result is not None
    assert result.reason == "STOP_FIRST_AMBIGUOUS"
    assert result.gross_r == -1.0
    assert abs(result.net_r + 1.10) < 1e-12


def test_v71_target_cannot_complete_on_entry_bar_but_can_next_bar():
    bars = (
        _bar(0, low=99.5, high=102.5),
        _bar(1, low=99.5, high=102.5),
    )
    result = resolve_forward_outcome(bars, evaluation=_evaluation())
    assert result is not None
    assert result.reason == "TARGET_HIT"
    assert result.bars_held == 1
    assert result.gross_r == 2.0
    assert abs(result.net_r - 1.90) < 1e-12


def test_v71_time_exit_matches_frozen_16_bar_horizon():
    bars = tuple(
        _bar(
            i,
            low=99.5,
            high=100.5,
            close=100.0 + (0.25 if i == MAX_HOLD_BARS else 0.0),
        )
        for i in range(MAX_HOLD_BARS + 1)
    )
    result = resolve_forward_outcome(bars, evaluation=_evaluation())
    assert result is not None
    assert result.reason == "TIME_EXIT"
    assert result.bars_held == MAX_HOLD_BARS
    assert abs(result.gross_r - 0.25) < 1e-12
    assert abs(result.net_r - 0.15) < 1e-12


def test_v71_stays_unresolved_before_hold_horizon():
    bars = tuple(_bar(i) for i in range(MAX_HOLD_BARS))
    assert resolve_forward_outcome(bars, evaluation=_evaluation()) is None


def test_v71_metrics_are_json_safe_when_no_losses():
    metrics = summarize_outcomes(
        [
            {"exit_at": "2026-09-21T01:00:00+00:00", "net_r": 1.0},
            {"exit_at": "2026-09-21T02:00:00+00:00", "net_r": 2.0},
        ]
    )
    assert metrics["profit_factor"] is None
    assert metrics["profit_factor_infinite"] is True
    assert metrics["net_r"] == 3.0

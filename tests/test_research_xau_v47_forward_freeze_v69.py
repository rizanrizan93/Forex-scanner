from datetime import timezone

from fx_scanner.research_xau_v47_forward_freeze_v69 import (
    BASE_ROUTE,
    EXECUTION_INFLUENCE,
    FORWARD_CONTRACT,
    MIN_PRIMARY_CLOSED_TRADES,
    MIN_REFERENCE_CLOSED_TRADES,
    POLICY_EFFECT,
    PROSPECTIVE_EPOCH,
    PROMOTION_ELIGIBLE,
    assess_forward_snapshot,
)


def test_v69_contract_is_prospective_and_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert BASE_ROUTE == "SECULAR_BULL_REACCEL_LONG_COST10"
    assert PROSPECTIVE_EPOCH.tzinfo == timezone.utc
    assert PROSPECTIVE_EPOCH.isoformat() == "2026-09-20T01:00:00+00:00"
    assert FORWARD_CONTRACT["live_money_promotion_allowed"] is False
    assert FORWARD_CONTRACT["flexible_lot_enabled"] is False
    assert FORWARD_CONTRACT["parameter_retuning_during_forward_test"] is False


def test_v69_sample_cannot_be_lowered():
    assert MIN_PRIMARY_CLOSED_TRADES == 30
    assert MIN_REFERENCE_CLOSED_TRADES == 30
    assert FORWARD_CONTRACT["minimum_sample_may_be_lowered_after_observing_forward_outcomes"] is False


def test_v69_pass_only_allows_limited_demo():
    result = assess_forward_snapshot(
        primary_closed_trades=30,
        reference_closed_trades=30,
        primary_profit_factor=1.30,
        reference_profit_factor=1.10,
        primary_expectancy_r=0.15,
        reference_expectancy_r=0.05,
        primary_net_r=4.5,
        primary_max_drawdown_r=3.0,
        reference_max_drawdown_r=4.0,
    )
    assert result["passed"] is True
    assert result["decision"] == "READY_FOR_LIMITED_DEMO_EXPERIMENT"
    assert result["live_money_promotion_allowed"] is False
    assert result["flexible_lot_enabled"] is False


def test_v69_fails_relative_edge_even_if_absolute_positive():
    result = assess_forward_snapshot(
        primary_closed_trades=40,
        reference_closed_trades=40,
        primary_profit_factor=1.20,
        reference_profit_factor=1.30,
        primary_expectancy_r=0.10,
        reference_expectancy_r=0.12,
        primary_net_r=4.0,
        primary_max_drawdown_r=3.0,
        reference_max_drawdown_r=4.0,
    )
    assert result["passed"] is False
    assert result["decision"] == "FORWARD_GATE_FAIL"

from fx_scanner.research_xau_v47_target_forward_freeze_v77 import (
    EXECUTION_INFLUENCE,
    FORWARD_CONTRACT,
    MIN_PRIMARY_CLOSED_TRADES,
    MIN_REFERENCE_CLOSED_TRADES,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    PROSPECTIVE_EPOCH,
    assess_forward_snapshot,
)


def test_v77_is_frozen_shadow_only_contract():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert PROSPECTIVE_EPOCH.isoformat() == "2026-09-20T03:00:00+00:00"
    assert MIN_PRIMARY_CLOSED_TRADES == 30
    assert MIN_REFERENCE_CLOSED_TRADES == 30
    assert FORWARD_CONTRACT["target_is_modified_by_experiment"] is False
    assert FORWARD_CONTRACT["stop_is_modified_by_experiment"] is False
    assert FORWARD_CONTRACT["entry_is_modified_by_experiment"] is False
    assert FORWARD_CONTRACT["independent_from_v69_sweep_experiment"] is True
    assert FORWARD_CONTRACT["may_rescue_or_override_v69"] is False


def test_v77_cannot_pass_before_frozen_minimum_sample():
    result = assess_forward_snapshot(
        primary_closed_trades=29,
        reference_closed_trades=100,
        primary_profit_factor=2.0,
        reference_profit_factor=1.0,
        primary_expectancy_r=0.20,
        reference_expectancy_r=0.01,
        primary_net_r=5.0,
        primary_max_drawdown_r=1.0,
        reference_max_drawdown_r=2.0,
    )
    assert result["passed"] is False
    assert result["decision"] == "FORWARD_SAMPLE_INSUFFICIENT"


def test_v77_pass_requires_absolute_and_relative_gates():
    result = assess_forward_snapshot(
        primary_closed_trades=30,
        reference_closed_trades=30,
        primary_profit_factor=1.20,
        reference_profit_factor=1.10,
        primary_expectancy_r=0.08,
        reference_expectancy_r=0.02,
        primary_net_r=2.4,
        primary_max_drawdown_r=2.0,
        reference_max_drawdown_r=2.5,
    )
    assert result["passed"] is True
    assert result["decision"] == "READY_FOR_LIMITED_DEMO_EXPERIMENT"
    assert result["execution_influence"] is False

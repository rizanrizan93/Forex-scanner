from __future__ import annotations

from datetime import datetime, timezone

RESEARCH_VERSION = "XAU_V47_TARGET_FORWARD_FREEZE_V77"
ARTIFACT_CONTRACT = "XAU_V47_TARGET_FORWARD_FREEZE_V77_CONTRACT_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

PROSPECTIVE_EPOCH = datetime(2026, 9, 20, 3, 0, 0, tzinfo=timezone.utc)

BASE_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
PRIMARY_CONTEXT = "TARGET_TO_PRIOR60_D1_MEDIAN_GT_0_75"
REFERENCE_CONTEXT = "TARGET_TO_PRIOR60_D1_MEDIAN_LE_0_75"

MIN_PRIMARY_CLOSED_TRADES = 30
MIN_REFERENCE_CLOSED_TRADES = 30
MIN_PRIMARY_PROFIT_FACTOR = 1.10
MIN_PRIMARY_EXPECTANCY_R = 0.05

FORWARD_CONTRACT = {
    "base_route": BASE_ROUTE,
    "primary_hypothesis": (
        "Among prospectively observed V47-approved XAU LONG reacceleration trades, "
        "trades whose unchanged frozen target distance exceeds 0.75 times the prior-60 "
        "completed-D1 median daily range have positive standalone expectancy and "
        "outperform contemporaneous V47 trades at or below 0.75."
    ),
    "primary_context": PRIMARY_CONTEXT,
    "reference_context": REFERENCE_CONTEXT,
    "prospective_epoch": PROSPECTIVE_EPOCH.isoformat(),
    "minimum_samples": {
        "primary_closed_trades": MIN_PRIMARY_CLOSED_TRADES,
        "reference_closed_trades": MIN_REFERENCE_CLOSED_TRADES,
    },
    "primary_absolute_gates": {
        "profit_factor_min": MIN_PRIMARY_PROFIT_FACTOR,
        "expectancy_r_min": MIN_PRIMARY_EXPECTANCY_R,
        "net_r_must_be_positive": True,
    },
    "primary_relative_gates": {
        "primary_expectancy_must_exceed_reference": True,
        "primary_profit_factor_must_exceed_reference": True,
        "primary_max_drawdown_r_must_not_exceed_reference": True,
    },
    "historical_basis": {
        "source_contract": "XAU_V47_TARGET_CREDIBILITY_V74_EVIDENCE_1",
        "threshold_was_predeclared_before_v74_outcomes": True,
        "historical_bucket_may_count_as_forward": False,
    },
    "target_is_modified_by_experiment": False,
    "stop_is_modified_by_experiment": False,
    "entry_is_modified_by_experiment": False,
    "independent_from_v69_sweep_experiment": True,
    "may_rescue_or_override_v69": False,
    "parameter_retuning_during_forward_test": False,
    "minimum_sample_may_be_lowered_after_observing_forward_outcomes": False,
    "promotion_if_passed": "READY_FOR_LIMITED_DEMO_EXPERIMENT_ONLY",
    "limited_demo_initial_lot": 0.01,
    "live_money_promotion_allowed": False,
    "flexible_lot_enabled": False,
    "execution_authority": False,
}


def assess_forward_snapshot(
    *,
    primary_closed_trades: int,
    reference_closed_trades: int,
    primary_profit_factor: float | None,
    reference_profit_factor: float | None,
    primary_expectancy_r: float | None,
    reference_expectancy_r: float | None,
    primary_net_r: float,
    primary_max_drawdown_r: float,
    reference_max_drawdown_r: float,
) -> dict[str, object]:
    sample_ready = (
        int(primary_closed_trades) >= MIN_PRIMARY_CLOSED_TRADES
        and int(reference_closed_trades) >= MIN_REFERENCE_CLOSED_TRADES
    )
    absolute = {
        "profit_factor": (
            primary_profit_factor is not None
            and float(primary_profit_factor) >= MIN_PRIMARY_PROFIT_FACTOR
        ),
        "expectancy": (
            primary_expectancy_r is not None
            and float(primary_expectancy_r) >= MIN_PRIMARY_EXPECTANCY_R
        ),
        "net_r": float(primary_net_r) > 0.0,
    }
    relative = {
        "expectancy_vs_reference": (
            primary_expectancy_r is not None
            and reference_expectancy_r is not None
            and float(primary_expectancy_r) > float(reference_expectancy_r)
        ),
        "profit_factor_vs_reference": (
            primary_profit_factor is not None
            and reference_profit_factor is not None
            and float(primary_profit_factor) > float(reference_profit_factor)
        ),
        "drawdown_vs_reference": (
            float(primary_max_drawdown_r) <= float(reference_max_drawdown_r)
        ),
    }
    passed = bool(
        sample_ready
        and all(absolute.values())
        and all(relative.values())
    )
    return {
        "sample_ready": sample_ready,
        "absolute_gates": absolute,
        "relative_gates": relative,
        "passed": passed,
        "decision": (
            "READY_FOR_LIMITED_DEMO_EXPERIMENT"
            if passed
            else ("FORWARD_SAMPLE_INSUFFICIENT" if not sample_ready else "FORWARD_GATE_FAIL")
        ),
        "execution_influence": False,
        "promotion_eligible": False,
        "live_money_promotion_allowed": False,
        "flexible_lot_enabled": False,
    }

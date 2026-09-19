from __future__ import annotations

from typing import Any, Mapping, Sequence

from .models import Bar
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_satellite_attribution_v59 import (
    ARTIFACT_CONTRACT as V59_ARTIFACT_CONTRACT,
    evaluate_v59,
)

RESEARCH_VERSION = "XAU_SATELLITE_DOMINANCE_GATE_V60"
ARTIFACT_CONTRACT = "XAU_SATELLITE_DOMINANCE_GATE_V60_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")


def _metric_positive(metrics: Mapping[str, Any]) -> bool:
    pf = metrics.get("profit_factor")
    exp = metrics.get("expectancy_r")
    return (
        pf is not None
        and exp is not None
        and float(pf) > 1.0
        and float(exp) > 0.0
    )


def _scenario_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    satellite = payload["satellite"]
    full = payload["full_period_attribution"]
    rolling = payload["rolling_3y"]

    positive_incremental_full = float(full["incremental_net_r"]) > 0.0
    no_full_period_dd_increase = float(full["drawdown_delta_r"]) <= 0.0
    satellite_standalone_positive = _metric_positive(satellite["metrics"])

    negative_windows: list[dict[str, Any]] = []
    zero_windows: list[str] = []
    positive_windows: list[str] = []
    for window, row in sorted(rolling.items()):
        core_trades = int(row["core"]["trades"])
        portfolio_trades = int(row["portfolio"]["trades"])
        if core_trades <= 0 and portfolio_trades <= 0:
            continue
        delta = float(row["delta"]["incremental_net_r"])
        if delta < 0.0:
            negative_windows.append(
                {
                    "window": window,
                    "incremental_net_r": delta,
                    "drawdown_delta_r": float(row["delta"]["drawdown_delta_r"]),
                }
            )
        elif delta > 0.0:
            positive_windows.append(window)
        else:
            zero_windows.append(window)

    no_negative_rolling_incremental = len(negative_windows) == 0
    passed = (
        positive_incremental_full
        and no_full_period_dd_increase
        and satellite_standalone_positive
        and no_negative_rolling_incremental
    )

    return {
        "passed": passed,
        "criteria": {
            "positive_incremental_full_period": positive_incremental_full,
            "no_full_period_drawdown_increase": no_full_period_dd_increase,
            "satellite_standalone_pf_gt_1_and_expectancy_gt_0": satellite_standalone_positive,
            "no_negative_rolling_3y_incremental_windows": no_negative_rolling_incremental,
        },
        "evidence": {
            "full_period_incremental_net_r": float(full["incremental_net_r"]),
            "full_period_drawdown_delta_r": float(full["drawdown_delta_r"]),
            "satellite_pf": satellite["metrics"].get("profit_factor"),
            "satellite_expectancy_r": satellite["metrics"].get("expectancy_r"),
            "negative_rolling_windows": negative_windows,
            "zero_incremental_windows": zero_windows,
            "positive_incremental_windows": positive_windows,
        },
    }


def evaluate_v60(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    v59 = evaluate_v59(
        bars,
        pip_size=pip_size,
        cost_scenarios=cost_scenarios,
    )
    missing = [cost for cost in REQUIRED_COSTS if cost not in v59["scenarios"]]
    if missing:
        raise ValueError(f"V60_MISSING_REQUIRED_COSTS:{missing}")

    costs: dict[str, Any] = {}
    for cost_id in REQUIRED_COSTS:
        costs[cost_id] = _scenario_gate(v59["scenarios"][cost_id])

    all_costs_pass = all(bool(costs[cost_id]["passed"]) for cost_id in REQUIRED_COSTS)

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "source_artifact_contract": V59_ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "gate_name": "BASELINE_RELATIVE_PARETO_DOMINANCE_ZERO_THRESHOLD",
        "preregistered_contract": {
            "required_costs": list(REQUIRED_COSTS),
            "full_period_incremental_net_r_must_be_positive": True,
            "full_period_drawdown_delta_must_be_le_zero": True,
            "satellite_standalone_pf_must_be_gt_1": True,
            "satellite_standalone_expectancy_must_be_gt_0": True,
            "every_observed_rolling_3y_incremental_net_r_must_be_nonnegative": True,
            "numeric_thresholds_tuned_from_v59": False,
            "v48_original_absolute_gate_replaced": False,
            "strategy_retuned": False,
            "execution_authority": False,
        },
        "cost_results": costs,
        "all_required_costs_pass": all_costs_pass,
        "decision": (
            "PASS_BASELINE_RELATIVE_DOMINANCE"
            if all_costs_pass
            else "FAIL_BASELINE_RELATIVE_DOMINANCE"
        ),
        "note": (
            "V60 formalizes a threshold-free, baseline-relative satellite gate. It does not "
            "change V48's original verdict. A satellite must add return without increasing "
            "full-period drawdown and without any negative rolling-three-year incremental window."
        ),
    }

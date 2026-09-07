from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any

MAX_DEMO_LOTS = 0.10
MIN_DEMO_LOTS = 0.01
MAX_DEMO_RISK_PCT = 10.0


@dataclass(frozen=True, slots=True)
class DemoConvictionSizing:
    tier: str
    lots: float
    risk_budget_pct: float


def select_demo_conviction_sizing(
    row: dict[str, Any],
    *,
    max_order_lots: float = MAX_DEMO_LOTS,
    max_risk_pct: float = MAX_DEMO_RISK_PCT,
) -> DemoConvictionSizing:
    """Map validated DEMO setup quality to bounded lot and risk budgets.

    The setup score is primary. Data coverage and planned TP2 RR are required for
    the larger tiers so a high score cannot by itself unlock maximum size. This
    function never changes Entry/SL/TP geometry and never permits >0.10 lot or
    >10 percentage points of configured DEMO risk budget.
    """
    try:
        score = float(row.get("final_score"))
        coverage = float(row.get("data_coverage"))
        rr2 = float(row.get("rr2"))
        order_cap = float(max_order_lots)
        risk_cap = float(max_risk_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("DEMO_CONVICTION_SIZING_INPUT_INVALID") from exc

    if not all(isfinite(value) for value in (score, coverage, rr2, order_cap, risk_cap)):
        raise ValueError("DEMO_CONVICTION_SIZING_INPUT_NONFINITE")
    if not 0.0 <= score <= 100.0 or not 0.0 <= coverage <= 1.0 or rr2 <= 0.0:
        raise ValueError("DEMO_CONVICTION_SIZING_QUALITY_INVALID")
    if order_cap < MIN_DEMO_LOTS or risk_cap <= 0.0:
        raise ValueError("DEMO_CONVICTION_SIZING_CAP_INVALID")

    if score >= 95.0 and coverage >= 0.95 and rr2 >= 2.50:
        tier, lots, risk = "ELITE", 0.10, 10.0
    elif score >= 90.0 and coverage >= 0.90 and rr2 >= 2.00:
        tier, lots, risk = "A_PLUS", 0.07, 7.0
    elif score >= 80.0 and coverage >= 0.90 and rr2 >= 2.00:
        tier, lots, risk = "A", 0.05, 5.0
    elif score >= 70.0 and coverage >= 0.85 and rr2 >= 1.75:
        tier, lots, risk = "B_PLUS", 0.03, 3.0
    elif score >= 60.0:
        tier, lots, risk = "B", 0.02, 2.0
    else:
        tier, lots, risk = "BASE", 0.01, 1.0

    return DemoConvictionSizing(
        tier=tier,
        lots=min(lots, MAX_DEMO_LOTS, order_cap),
        risk_budget_pct=min(risk, MAX_DEMO_RISK_PCT, risk_cap),
    )


def _install_runtime_policy_cap() -> None:
    """Raise only cTrader DEMO runtime lot/risk caps to approved ceilings."""
    from . import demo_calibration_autotrade as runtime

    if getattr(runtime, "_demo_conviction_policy_patch_installed", False):
        return

    original = runtime.load_execution_policy

    def _load_execution_policy_with_conviction_cap(root=None):
        policy = original(root)
        demo_safety = dict(policy.demo_safety)
        demo_safety["max_order_lots"] = MAX_DEMO_LOTS
        demo_safety["max_risk_pct"] = MAX_DEMO_RISK_PCT
        return replace(policy, demo_safety=demo_safety)

    runtime.load_execution_policy = _load_execution_policy_with_conviction_cap
    runtime._demo_conviction_policy_patch_installed = True


def _install_executor_sizing() -> None:
    """Apply conviction sizing after all existing signal/quote/geometry gates pass."""
    from .execution.demo_autotrade import CTraderDemoAutoExecutor

    if getattr(CTraderDemoAutoExecutor, "_demo_conviction_sizing_installed", False):
        return

    original = CTraderDemoAutoExecutor._intent_diagnostic

    def _intent_diagnostic_with_conviction(self, row, *, now):
        intent, reason = original(self, row, now=now)
        if intent is None:
            return None, reason
        try:
            sizing = select_demo_conviction_sizing(
                row,
                max_order_lots=min(
                    MAX_DEMO_LOTS,
                    float(self.demo.get("max_order_lots", MAX_DEMO_LOTS)),
                ),
                max_risk_pct=min(
                    MAX_DEMO_RISK_PCT,
                    float(self.demo.get("max_risk_pct", MAX_DEMO_RISK_PCT)),
                ),
            )
        except Exception as exc:
            return None, f"CONVICTION_SIZING_INVALID:{type(exc).__name__}"

        return (
            replace(
                intent,
                volume=sizing.lots,
                risk_pct=sizing.risk_budget_pct,
                comment=f"{intent.comment}:{sizing.tier}",
            ),
            None,
        )

    CTraderDemoAutoExecutor._intent_diagnostic = _intent_diagnostic_with_conviction
    CTraderDemoAutoExecutor._demo_conviction_sizing_installed = True


def install_demo_conviction_sizing() -> None:
    """Install DEMO-only 0.01-0.10 lot / 1%-10% setup-weighted sizing."""
    _install_runtime_policy_cap()
    _install_executor_sizing()

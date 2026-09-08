from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any

MAX_DEMO_LOTS = 0.01
MIN_DEMO_LOTS = 0.01
MAX_DEMO_RISK_PCT = 3.0


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
    """Map validated DEMO setup quality to bounded risk budgets.

    Lot size remains fixed at the 0.01-lot calibration cap for every tier.
    Entry/SL/TP geometry is never changed here and the DEMO risk-budget contract
    remains capped at 3 percentage points.
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
        tier, risk = "ELITE", 3.0
    elif score >= 90.0 and coverage >= 0.90 and rr2 >= 2.00:
        tier, risk = "A_PLUS", 2.5
    elif score >= 80.0 and coverage >= 0.90 and rr2 >= 2.00:
        tier, risk = "A", 2.0
    elif score >= 70.0 and coverage >= 0.85 and rr2 >= 1.75:
        tier, risk = "B_PLUS", 1.5
    elif score >= 60.0:
        tier, risk = "B", 1.0
    else:
        tier, risk = "BASE", 0.5

    return DemoConvictionSizing(
        tier=tier,
        lots=min(MIN_DEMO_LOTS, MAX_DEMO_LOTS, order_cap),
        risk_budget_pct=min(risk, MAX_DEMO_RISK_PCT, risk_cap),
    )


def _install_runtime_policy_cap() -> None:
    """Enforce the cTrader DEMO runtime order cap at 0.01 lot."""
    from . import demo_calibration_autotrade as runtime

    if getattr(runtime, "_demo_conviction_policy_patch_installed", False):
        return

    original = runtime.load_execution_policy

    def _load_execution_policy_with_conviction_cap(root=None):
        policy = original(root)
        demo_safety = dict(policy.demo_safety)
        demo_safety["max_order_lots"] = min(
            MAX_DEMO_LOTS,
            float(demo_safety.get("max_order_lots", MAX_DEMO_LOTS)),
        )
        return replace(policy, demo_safety=demo_safety)

    runtime.load_execution_policy = _load_execution_policy_with_conviction_cap
    runtime._demo_conviction_policy_patch_installed = True


def _install_executor_sizing() -> None:
    """Apply bounded risk sizing after all existing signal/quote/geometry gates pass."""
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

        risk_pct = min(float(intent.risk_pct), sizing.risk_budget_pct)
        return (
            replace(
                intent,
                volume=sizing.lots,
                risk_pct=risk_pct,
                comment=f"{intent.comment}:{sizing.tier}",
            ),
            None,
        )

    CTraderDemoAutoExecutor._intent_diagnostic = _intent_diagnostic_with_conviction
    CTraderDemoAutoExecutor._demo_conviction_sizing_installed = True


def install_demo_conviction_sizing() -> None:
    """Install DEMO-only fixed 0.01-lot sizing with bounded conviction risk."""
    _install_runtime_policy_cap()
    _install_executor_sizing()

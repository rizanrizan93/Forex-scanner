from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..exceptions import DataContractError
from .metrics import PerformanceMetrics
from .monte_carlo import MonteCarloResult
from .walk_forward import WalkForwardResult


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    passed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _metric_gate(
    name: str,
    metrics: PerformanceMetrics,
    *,
    minimum_trades: int,
    win_rate_min: float,
    profit_factor_min: float,
    expectancy_r_min: float,
) -> list[str]:
    blockers: list[str] = []
    if metrics.completed_trades < minimum_trades:
        blockers.append(f"{name}:SAMPLE<{minimum_trades}")
    if metrics.win_rate is None or metrics.win_rate < win_rate_min:
        blockers.append(f"{name}:WIN_RATE<{win_rate_min:.4f}")
    if metrics.profit_factor is None or metrics.profit_factor < profit_factor_min:
        blockers.append(f"{name}:PF<{profit_factor_min:.4f}")
    if metrics.expectancy_r is None or metrics.expectancy_r < expectancy_r_min:
        blockers.append(f"{name}:EXPECTANCY<{expectancy_r_min:.4f}R")
    return blockers


def evaluate_acceptance(
    *,
    base_oos: PerformanceMetrics,
    stressed_oos: PerformanceMetrics,
    walk_forward: WalkForwardResult,
    monte_carlo: MonteCarloResult,
    regime_metrics: Mapping[str, PerformanceMetrics],
    acceptance_cfg: Mapping,
    validation_cfg: Mapping,
) -> AcceptanceDecision:
    blockers: list[str] = []
    warnings: list[str] = []

    required = (
        "oos_win_rate_min",
        "profit_factor_min",
        "expectancy_r_min",
        "aggregate_oos_trades_min",
    )
    if any(key not in acceptance_cfg for key in required):
        raise DataContractError("acceptance configuration is incomplete")

    blockers.extend(
        _metric_gate(
            "BASE_OOS",
            base_oos,
            minimum_trades=int(acceptance_cfg["aggregate_oos_trades_min"]),
            win_rate_min=float(acceptance_cfg["oos_win_rate_min"]),
            profit_factor_min=float(acceptance_cfg["profit_factor_min"]),
            expectancy_r_min=float(acceptance_cfg["expectancy_r_min"]),
        )
    )

    stress_cfg = validation_cfg["stress_acceptance"]
    blockers.extend(
        _metric_gate(
            "STRESS_OOS",
            stressed_oos,
            minimum_trades=int(acceptance_cfg["aggregate_oos_trades_min"]),
            win_rate_min=float(stress_cfg["win_rate_min"]),
            profit_factor_min=float(stress_cfg["profit_factor_min"]),
            expectancy_r_min=float(stress_cfg["expectancy_r_min"]),
        )
    )

    if not walk_forward.passed:
        blockers.append("WALK_FORWARD_FAIL")

    mc_cfg = validation_cfg["monte_carlo"]
    if monte_carlo.max_drawdown_r_p95 > float(mc_cfg["max_drawdown_r_p95_limit"]):
        blockers.append("MONTE_CARLO_DRAWDOWN_P95_FAIL")
    if monte_carlo.losing_streak_p95 > int(mc_cfg["losing_streak_p95_limit"]):
        blockers.append("MONTE_CARLO_LOSS_STREAK_P95_FAIL")

    regime_cfg = validation_cfg["regimes"]
    minimum_trades = int(regime_cfg["minimum_trades_per_regime"])
    eligible = {
        name: metrics
        for name, metrics in regime_metrics.items()
        if metrics.completed_trades >= minimum_trades
    }
    if len(eligible) < int(regime_cfg["minimum_eligible_regimes"]):
        blockers.append("MULTI_REGIME_INSUFFICIENT_COVERAGE")
    for name, metrics in eligible.items():
        if metrics.expectancy_r is None or metrics.expectancy_r < float(regime_cfg["minimum_expectancy_r"]):
            blockers.append(f"REGIME:{name}:EXPECTANCY_FAIL")
        if metrics.profit_factor is None or metrics.profit_factor < float(regime_cfg["minimum_profit_factor"]):
            blockers.append(f"REGIME:{name}:PF_FAIL")

    if base_oos.max_drawdown_r > monte_carlo.max_drawdown_r_p95:
        warnings.append("REALIZED_DRAWDOWN_ABOVE_MC_P95")

    return AcceptanceDecision(not blockers, tuple(sorted(set(blockers))), tuple(sorted(set(warnings))))

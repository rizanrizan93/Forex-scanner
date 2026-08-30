from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..exceptions import DataContractError
from ..models import Bar
from .acceptance import AcceptanceDecision, evaluate_acceptance
from .backtest import BacktestEngine, BacktestResult, CostModel, TradeIntent
from .metrics import PerformanceMetrics, compute_metrics, metrics_by_group
from .monte_carlo import MonteCarloResult, monte_carlo_returns
from .perturbation import PerturbationResult
from .split import ChronologicalSplit, chronological_split
from .walk_forward import WalkForwardResult, walk_forward_evaluate


@dataclass(frozen=True, slots=True)
class ExternalValidationChecks:
    demo_forward_passed: bool = False
    parameter_perturbation: PerturbationResult | None = None


@dataclass(frozen=True, slots=True)
class ValidationSuiteReport:
    split: ChronologicalSplit
    development: BacktestResult
    oos_base: BacktestResult
    oos_stressed: BacktestResult
    base_metrics: PerformanceMetrics
    stressed_metrics: PerformanceMetrics
    regime_metrics: Mapping[str, PerformanceMetrics]
    setup_metrics: Mapping[str, PerformanceMetrics]
    symbol_metrics: Mapping[str, PerformanceMetrics]
    walk_forward: WalkForwardResult
    monte_carlo: MonteCarloResult | None
    acceptance: AcceptanceDecision


def _cost_model(cfg: Mapping, *, stressed: bool) -> CostModel:
    base = cfg["costs"]["base"]
    model = CostModel(
        spread_pips=float(base["spread_pips"]),
        slippage_pips=float(base["slippage_pips"]),
        commission_pips_round_trip=float(base["commission_pips_round_trip"]),
        swap_pips_per_day=float(base["swap_pips_per_day"]),
    )
    if stressed:
        return model.stressed(
            spread_multiplier=float(cfg["costs"]["stress_spread_multiplier"]),
            slippage_multiplier=float(cfg["costs"]["stress_slippage_multiplier"]),
        )
    return model


def run_validation_suite(
    *,
    intents: Sequence[TradeIntent],
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    timeframe_seconds: int,
    acceptance_cfg: Mapping,
    validation_cfg: Mapping,
    external_checks: ExternalValidationChecks | None = None,
) -> ValidationSuiteReport:
    external_checks = external_checks or ExternalValidationChecks()
    split_cfg = validation_cfg["dataset_split"]
    split = chronological_split(
        intents,
        train_fraction=float(split_cfg["train_fraction"]),
        validation_fraction=float(split_cfg["validation_fraction"]),
        oos_fraction=float(split_cfg["oos_fraction"]),
    )

    engine_cfg = validation_cfg["engine"]
    base_engine = BacktestEngine(
        cost_model=_cost_model(validation_cfg, stressed=False),
        ambiguous_bar_policy=str(engine_cfg["ambiguous_bar_policy"]),
        minimum_stop_distance_pips=float(engine_cfg["minimum_stop_distance_pips"]),
    )
    stress_engine = BacktestEngine(
        cost_model=_cost_model(validation_cfg, stressed=True),
        ambiguous_bar_policy=str(engine_cfg["ambiguous_bar_policy"]),
        minimum_stop_distance_pips=float(engine_cfg["minimum_stop_distance_pips"]),
    )

    development_intents = (*split.train, *split.validation)
    development = base_engine.run(
        development_intents,
        bars_by_symbol,
        timeframe_seconds=timeframe_seconds,
    )
    oos_base = base_engine.run(split.oos, bars_by_symbol, timeframe_seconds=timeframe_seconds)
    oos_stressed = stress_engine.run(split.oos, bars_by_symbol, timeframe_seconds=timeframe_seconds)

    base_metrics = compute_metrics(oos_base.trades)
    stressed_metrics = compute_metrics(oos_stressed.trades)
    regime_metrics = metrics_by_group(oos_base.trades, field="regime")
    setup_metrics = metrics_by_group(oos_base.trades, field="setup")
    symbol_metrics = metrics_by_group(oos_base.trades, field="symbol")

    wf_cfg = validation_cfg["walk_forward"]
    walk_forward = walk_forward_evaluate(
        development.trades,
        train_fraction=float(wf_cfg["train_fraction"]),
        test_fraction=float(wf_cfg["test_fraction"]),
        step_fraction=float(wf_cfg["step_fraction"]),
        minimum_train_trades=int(wf_cfg["minimum_train_trades"]),
        minimum_test_trades=int(wf_cfg["minimum_test_trades"]),
        fold_win_rate_min=float(wf_cfg["fold_win_rate_min"]),
        fold_profit_factor_min=float(wf_cfg["fold_profit_factor_min"]),
        fold_expectancy_r_min=float(wf_cfg["fold_expectancy_r_min"]),
        minimum_pass_fraction=float(wf_cfg["minimum_pass_fraction"]),
    )

    completed_returns = [
        float(x.net_r)
        for x in oos_base.completed
        if x.net_r is not None
    ]
    mc: MonteCarloResult | None
    if completed_returns:
        mc_cfg = validation_cfg["monte_carlo"]
        mc = monte_carlo_returns(
            completed_returns,
            simulations=int(mc_cfg["simulations"]),
            seed=int(mc_cfg["seed"]),
            block_size=int(mc_cfg["block_size"]),
        )
    else:
        mc = None

    acceptance = evaluate_acceptance(
        base_oos=base_metrics,
        stressed_oos=stressed_metrics,
        walk_forward=walk_forward,
        monte_carlo=mc,
        regime_metrics=regime_metrics,
        acceptance_cfg=acceptance_cfg,
        validation_cfg=validation_cfg,
        demo_forward_passed=external_checks.demo_forward_passed,
        parameter_perturbation=external_checks.parameter_perturbation,
    )
    return ValidationSuiteReport(
        split,
        development,
        oos_base,
        oos_stressed,
        base_metrics,
        stressed_metrics,
        regime_metrics,
        setup_metrics,
        symbol_metrics,
        walk_forward,
        mc,
        acceptance,
    )

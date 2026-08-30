from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Sequence

from ..exceptions import DataContractError
from .backtest import BacktestTrade, TradeOutcome
from .metrics import PerformanceMetrics, compute_metrics


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_metrics: PerformanceMetrics
    test_metrics: PerformanceMetrics
    passed: bool


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    pass_fraction: float
    passed: bool


def _eligible(trades: Sequence[BacktestTrade]) -> list[BacktestTrade]:
    completed = [
        x for x in trades
        if x.outcome in {TradeOutcome.WIN, TradeOutcome.LOSS, TradeOutcome.BREAKEVEN}
        and x.net_r is not None
        and x.exit_at is not None
    ]
    completed.sort(key=lambda x: (x.exit_at, x.intent.symbol, x.intent.trade_id))
    return completed


def walk_forward_evaluate(
    trades: Sequence[BacktestTrade],
    *,
    train_fraction: float,
    test_fraction: float,
    step_fraction: float,
    minimum_train_trades: int,
    minimum_test_trades: int,
    fold_win_rate_min: float,
    fold_profit_factor_min: float,
    fold_expectancy_r_min: float,
    minimum_pass_fraction: float,
) -> WalkForwardResult:
    values = _eligible(trades)
    n = len(values)
    for name, fraction in (
        ("train_fraction", train_fraction),
        ("test_fraction", test_fraction),
        ("step_fraction", step_fraction),
        ("minimum_pass_fraction", minimum_pass_fraction),
    ):
        if not 0 < fraction <= 1:
            raise DataContractError(f"{name} must be in (0,1]")
    if train_fraction + test_fraction > 1:
        raise DataContractError("walk-forward train+test fractions cannot exceed 1")
    if minimum_train_trades <= 0 or minimum_test_trades <= 0:
        raise DataContractError("walk-forward minimum trade counts must be positive")

    train_size = max(minimum_train_trades, floor(n * train_fraction))
    test_size = max(minimum_test_trades, floor(n * test_fraction))
    step = max(1, floor(n * step_fraction))
    folds: list[WalkForwardFold] = []
    fold_no = 1
    start = 0

    while start + train_size + test_size <= n:
        train_end = start + train_size
        test_end = train_end + test_size
        train = values[start:train_end]
        test = values[train_end:test_end]
        train_metrics = compute_metrics(train)
        test_metrics = compute_metrics(test)
        passed = bool(
            test_metrics.completed_trades >= minimum_test_trades
            and test_metrics.win_rate is not None
            and test_metrics.win_rate >= fold_win_rate_min
            and test_metrics.profit_factor is not None
            and test_metrics.profit_factor >= fold_profit_factor_min
            and test_metrics.expectancy_r is not None
            and test_metrics.expectancy_r >= fold_expectancy_r_min
        )
        folds.append(
            WalkForwardFold(
                fold_no,
                start,
                train_end,
                train_end,
                test_end,
                train_metrics,
                test_metrics,
                passed,
            )
        )
        fold_no += 1
        start += step

    if not folds:
        return WalkForwardResult((), 0.0, False)
    pass_fraction = sum(1 for fold in folds if fold.passed) / len(folds)
    return WalkForwardResult(tuple(folds), pass_fraction, pass_fraction >= minimum_pass_fraction)

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping, Sequence

from ..exceptions import DataContractError
from .backtest import BacktestTrade, TradeOutcome


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    completed_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float | None
    profit_factor: float | None
    expectancy_r: float | None
    gross_profit_r: float
    gross_loss_r: float
    max_drawdown_r: float
    max_losing_streak: int
    average_cost_r: float | None

    def __post_init__(self) -> None:
        if min(self.completed_trades, self.wins, self.losses, self.breakeven) < 0:
            raise DataContractError("performance counts cannot be negative")
        if self.wins + self.losses + self.breakeven != self.completed_trades:
            raise DataContractError("performance trade-count mismatch")
        for name in ("win_rate", "profit_factor", "expectancy_r", "average_cost_r"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isfinite(float(value))):
                raise DataContractError(f"{name} must be finite when present")
        if self.win_rate is not None and not 0 <= self.win_rate <= 1:
            raise DataContractError("win_rate must be in [0,1]")
        if self.profit_factor is not None and self.profit_factor < 0:
            raise DataContractError("profit_factor cannot be negative")
        if self.gross_profit_r < 0 or self.gross_loss_r < 0 or self.max_drawdown_r < 0:
            raise DataContractError("gross/drawdown metrics cannot be negative")
        if self.max_losing_streak < 0:
            raise DataContractError("max_losing_streak cannot be negative")


def _completed(trades: Iterable[BacktestTrade]) -> list[BacktestTrade]:
    return [
        trade for trade in trades
        if trade.outcome in {TradeOutcome.WIN, TradeOutcome.LOSS, TradeOutcome.BREAKEVEN}
        and trade.net_r is not None
    ]


def _max_drawdown(returns: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _max_losing_streak(returns: Sequence[float]) -> int:
    current = 0
    maximum = 0
    for value in returns:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def compute_metrics(trades: Iterable[BacktestTrade]) -> PerformanceMetrics:
    completed = _completed(trades)
    if not completed:
        return PerformanceMetrics(0, 0, 0, 0, None, None, None, 0.0, 0.0, 0.0, 0, None)

    returns = [float(x.net_r) for x in completed]
    costs = [float(x.cost_r or 0.0) for x in completed]
    wins = sum(1 for x in returns if x > 0)
    losses = sum(1 for x in returns if x < 0)
    breakeven = len(returns) - wins - losses
    gross_profit = sum(x for x in returns if x > 0)
    gross_loss = abs(sum(x for x in returns if x < 0))
    profit_factor = None if gross_loss <= 1e-12 else gross_profit / gross_loss

    return PerformanceMetrics(
        completed_trades=len(returns),
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=wins / len(returns),
        profit_factor=profit_factor,
        expectancy_r=sum(returns) / len(returns),
        gross_profit_r=gross_profit,
        gross_loss_r=gross_loss,
        max_drawdown_r=_max_drawdown(returns),
        max_losing_streak=_max_losing_streak(returns),
        average_cost_r=sum(costs) / len(costs),
    )


def metrics_by_group(
    trades: Iterable[BacktestTrade],
    *,
    field: str,
) -> Mapping[str, PerformanceMetrics]:
    if field not in {"setup", "regime", "symbol"}:
        raise DataContractError("group field must be setup, regime, or symbol")
    groups: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        if field == "symbol":
            key = trade.intent.symbol
        else:
            key = str(getattr(trade.intent, field))
        groups.setdefault(key, []).append(trade)
    return {key: compute_metrics(value) for key, value in sorted(groups.items())}

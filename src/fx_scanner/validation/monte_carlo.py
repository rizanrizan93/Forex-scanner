from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
from random import Random
from typing import Sequence

from ..exceptions import DataContractError


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    simulations: int
    max_drawdown_r_p50: float
    max_drawdown_r_p95: float
    losing_streak_p50: int
    losing_streak_p95: int
    terminal_r_p05: float
    terminal_r_p50: float

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise DataContractError("Monte Carlo simulations must be positive")
        for value in (
            self.max_drawdown_r_p50,
            self.max_drawdown_r_p95,
            self.terminal_r_p05,
            self.terminal_r_p50,
        ):
            if not isfinite(value):
                raise DataContractError("Monte Carlo outputs must be finite")


def _drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _streak(values: Sequence[float]) -> int:
    current = maximum = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise DataContractError("percentile requires values")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(quantile * len(ordered)) - 1))
    return float(ordered[index])


def monte_carlo_returns(
    returns_r: Sequence[float],
    *,
    simulations: int = 1000,
    seed: int = 260830,
) -> MonteCarloResult:
    values = tuple(float(x) for x in returns_r)
    if not values or any(not isfinite(x) for x in values):
        raise DataContractError("Monte Carlo requires finite non-empty returns")
    if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations <= 0:
        raise DataContractError("simulations must be a positive integer")
    if simulations > 100_000:
        raise DataContractError("simulations exceeds safety bound")

    rng = Random(seed)
    drawdowns: list[float] = []
    streaks: list[int] = []
    terminals: list[float] = []
    work = list(values)
    for _ in range(simulations):
        rng.shuffle(work)
        drawdowns.append(_drawdown(work))
        streaks.append(_streak(work))
        terminals.append(sum(work))

    return MonteCarloResult(
        simulations,
        _percentile(drawdowns, 0.50),
        _percentile(drawdowns, 0.95),
        int(_percentile(streaks, 0.50)),
        int(_percentile(streaks, 0.95)),
        _percentile(terminals, 0.05),
        _percentile(terminals, 0.50),
    )

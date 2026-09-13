from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from math import inf, isfinite
from statistics import median
from typing import Iterable, Literal

from .models import Bar

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class BreakoutCandidate:
    name: str
    lookback: int
    atr_stop: float
    target_r: float
    compression_ratio_max: float | None
    expansion_atr_min: float


# Frozen before validation/OOS results are read.
FROZEN_CANDIDATES = (
    BreakoutCandidate(
        name="H1_DONCHIAN20_TREND_2R",
        lookback=20,
        atr_stop=2.0,
        target_r=2.0,
        compression_ratio_max=None,
        expansion_atr_min=0.0,
    ),
    BreakoutCandidate(
        name="H1_COMP20_TREND_2R",
        lookback=20,
        atr_stop=1.5,
        target_r=2.0,
        compression_ratio_max=4.0,
        expansion_atr_min=1.0,
    ),
    BreakoutCandidate(
        name="H1_COMP20_TREND_2P5R",
        lookback=20,
        atr_stop=1.5,
        target_r=2.5,
        compression_ratio_max=4.0,
        expansion_atr_min=1.0,
    ),
    BreakoutCandidate(
        name="H1_DONCHIAN55_TREND_2R",
        lookback=55,
        atr_stop=2.0,
        target_r=2.0,
        compression_ratio_max=None,
        expansion_atr_min=0.0,
    ),
)


@dataclass(frozen=True, slots=True)
class BreakoutTrade:
    symbol: str
    candidate: str
    direction: Direction
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    gross_r: float
    net_r: float
    exit_reason: str


@dataclass(frozen=True, slots=True)
class BreakoutSummary:
    trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    total_net_r: float
    max_drawdown_r: float


def pip_size(symbol: str) -> float:
    value = str(symbol).upper().replace("/", "")
    return 0.01 if value.endswith("JPY") else 0.0001


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2.0 / (period + 1.0)
    current = seed
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        result[index] = current
    return result


def _atr(rows: tuple[Bar, ...], period: int = 14) -> list[float | None]:
    tr: list[float] = []
    for index, row in enumerate(rows):
        if index == 0:
            value = row.high - row.low
        else:
            previous_close = rows[index - 1].close
            value = max(
                row.high - row.low,
                abs(row.high - previous_close),
                abs(row.low - previous_close),
            )
        tr.append(max(0.0, float(value)))
    result: list[float | None] = [None] * len(rows)
    if len(tr) < period:
        return result
    current = sum(tr[:period]) / period
    result[period - 1] = current
    for index in range(period, len(tr)):
        current = ((period - 1) * current + tr[index]) / period
        result[index] = current
    return result


def _validate(rows: Iterable[Bar]) -> tuple[Bar, ...]:
    ordered = tuple(sorted(rows, key=lambda row: row.timestamp))
    if not ordered:
        return ordered
    symbol = ordered[0].symbol
    for row in ordered:
        if row.symbol != symbol or row.timeframe != "H1":
            raise ValueError("H1 breakout replay accepts one symbol and H1 bars only")
        if row.timestamp.tzinfo is None or row.timestamp.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone-aware")
    if any(b.timestamp <= a.timestamp for a, b in zip(ordered, ordered[1:])):
        raise ValueError("bar timestamps must be strictly increasing")
    return ordered


def _max_drawdown(trades: Iterable[BreakoutTrade]) -> float:
    equity = peak = worst = 0.0
    for trade in sorted(trades, key=lambda row: row.entry_time):
        equity += trade.net_r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def summarize(trades: Iterable[BreakoutTrade]) -> BreakoutSummary:
    rows = tuple(sorted(trades, key=lambda row: row.entry_time))
    if not rows:
        return BreakoutSummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    positive = [row.net_r for row in rows if row.net_r > 0]
    negative = [row.net_r for row in rows if row.net_r < 0]
    gross_profit = sum(positive)
    gross_loss = -sum(negative)
    return BreakoutSummary(
        trades=len(rows),
        wins=len(positive),
        losses=len(negative),
        win_rate=len(positive) / len(rows),
        expectancy_r=sum(row.net_r for row in rows) / len(rows),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else inf,
        total_net_r=sum(row.net_r for row in rows),
        max_drawdown_r=_max_drawdown(rows),
    )


def reprice_cost(
    trades: Iterable[BreakoutTrade], *, round_trip_cost_pips: float
) -> tuple[BreakoutTrade, ...]:
    if round_trip_cost_pips < 0:
        raise ValueError("round-trip cost must be non-negative")
    output: list[BreakoutTrade] = []
    for trade in trades:
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk <= 0:
            raise ValueError("trade has non-positive initial risk")
        cost_r = round_trip_cost_pips * pip_size(trade.symbol) / risk
        output.append(replace(trade, net_r=trade.gross_r - cost_r))
    return tuple(output)


def replay_candidate(
    bars: Iterable[Bar],
    *,
    candidate: BreakoutCandidate,
    max_hold_bars: int = 72,
) -> tuple[BreakoutTrade, ...]:
    rows = _validate(bars)
    if not rows:
        return ()
    if max_hold_bars < 1:
        raise ValueError("max_hold_bars must be positive")

    closes = [float(row.close) for row in rows]
    ema200 = _ema(closes, 200)
    atr14 = _atr(rows, 14)
    warmup = max(200, candidate.lookback + 1)
    output: list[BreakoutTrade] = []
    next_allowed_index = warmup

    for index in range(warmup, len(rows) - 1):
        if index < next_allowed_index:
            continue
        atr = atr14[index - 1]
        ema = ema200[index - 1]
        if atr is None or ema is None or atr <= 0:
            continue
        prior = rows[index - candidate.lookback:index]
        high = max(float(row.high) for row in prior)
        low = min(float(row.low) for row in prior)
        decision = rows[index]
        direction: Direction | None = None
        if decision.close > high and decision.close > ema:
            direction = "LONG"
        elif decision.close < low and decision.close < ema:
            direction = "SHORT"
        if direction is None:
            continue

        if candidate.compression_ratio_max is not None:
            width = high - low
            if width / atr > candidate.compression_ratio_max:
                continue
            true_range = max(
                decision.high - decision.low,
                abs(decision.high - rows[index - 1].close),
                abs(decision.low - rows[index - 1].close),
            )
            if true_range / atr < candidate.expansion_atr_min:
                continue

        entry_index = index + 1
        entry = rows[entry_index]
        entry_price = float(entry.open)
        stop_distance = candidate.atr_stop * atr
        if stop_distance <= 0:
            continue
        if direction == "LONG":
            stop = entry_price - stop_distance
            target = entry_price + candidate.target_r * stop_distance
        else:
            stop = entry_price + stop_distance
            target = entry_price - candidate.target_r * stop_distance

        exit_index = min(len(rows) - 1, entry_index + max_hold_bars - 1)
        exit_reason = "TIME_EXIT"
        exit_price = float(rows[exit_index].close)
        actual_exit_index = exit_index
        gross_r = (
            (exit_price - entry_price) / stop_distance
            if direction == "LONG"
            else (entry_price - exit_price) / stop_distance
        )
        for probe_index in range(entry_index, exit_index + 1):
            probe = rows[probe_index]
            if direction == "LONG":
                stop_hit = probe.low <= stop
                target_hit = probe.high >= target
            else:
                stop_hit = probe.high >= stop
                target_hit = probe.low <= target
            # Conservative ambiguity rule from validation.yaml: STOP_FIRST.
            if stop_hit:
                gross_r = -1.0
                exit_price = stop
                exit_reason = "STOP"
                actual_exit_index = probe_index
                break
            if target_hit:
                gross_r = candidate.target_r
                exit_price = target
                exit_reason = "TARGET"
                actual_exit_index = probe_index
                break
        if not isfinite(gross_r):
            continue
        output.append(
            BreakoutTrade(
                symbol=rows[0].symbol,
                candidate=candidate.name,
                direction=direction,
                decision_time=decision.timestamp,
                entry_time=entry.timestamp,
                exit_time=rows[actual_exit_index].timestamp,
                entry_price=entry_price,
                stop_loss=stop,
                take_profit=target,
                gross_r=float(gross_r),
                net_r=float(gross_r),
                exit_reason=exit_reason,
            )
        )
        next_allowed_index = actual_exit_index + 1
    return tuple(output)


def split_calendar(
    trades: Iterable[BreakoutTrade],
    *,
    train_end: date,
    validation_end: date,
    oos_end: date,
) -> dict[str, tuple[BreakoutTrade, ...]]:
    if not train_end < validation_end < oos_end:
        raise ValueError("invalid calendar split")
    result = {"train": [], "validation": [], "oos": []}
    for trade in sorted(trades, key=lambda row: row.entry_time):
        day = trade.entry_time.date()
        if day <= train_end:
            result["train"].append(trade)
        elif day <= validation_end:
            result["validation"].append(trade)
        elif day <= oos_end:
            result["oos"].append(trade)
    return {key: tuple(value) for key, value in result.items()}


def summary_payload(trades: Iterable[BreakoutTrade]) -> dict[str, object]:
    return asdict(summarize(trades))

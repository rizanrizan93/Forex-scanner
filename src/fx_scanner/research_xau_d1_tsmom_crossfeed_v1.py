from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from random import Random

from .models import Bar

SEED = 20260913
BOUNDARY_HOURS_UTC = (0, 21, 22)
BASE_COST_USD = 0.17
STRESS_COST_USD = 0.35


@dataclass(frozen=True, slots=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Trade:
    signal_day: date
    entry_day: date
    exit_day: date
    direction: int
    entry: float
    stop: float
    target: float
    risk_price: float
    gross_r: float
    exit_reason: str


@dataclass(frozen=True, slots=True)
class Summary:
    trades: int
    net_r: float
    expectancy_r: float
    profit_factor: float
    win_rate: float
    max_drawdown_r: float
    bootstrap_positive_fraction_100: float


def resample_h1_to_daily(bars: tuple[Bar, ...], *, boundary_hour_utc: int) -> tuple[DailyBar, ...]:
    if boundary_hour_utc not in BOUNDARY_HOURS_UTC:
        raise ValueError(f"unsupported daily boundary hour: {boundary_hour_utc}")
    by_day: dict[date, list[Bar]] = {}
    shift = timedelta(hours=boundary_hour_utc)
    for bar in sorted(bars, key=lambda row: row.timestamp):
        key = (bar.timestamp - shift).date()
        by_day.setdefault(key, []).append(bar)

    rows: list[DailyBar] = []
    for day, items in sorted(by_day.items()):
        items = sorted(items, key=lambda row: row.timestamp)
        if len(items) < 18:
            continue
        rows.append(
            DailyBar(
                day=day,
                open=float(items[0].open),
                high=max(float(row.high) for row in items),
                low=min(float(row.low) for row in items),
                close=float(items[-1].close),
            )
        )
    return tuple(rows)


def _ema(values: list[float], span: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if not values:
        return out
    alpha = 2.0 / (span + 1.0)
    value = values[0]
    if span == 1:
        out[0] = value
    for idx in range(1, len(values)):
        value = alpha * values[idx] + (1.0 - alpha) * value
        if idx >= span - 1:
            out[idx] = value
    return out


def _wilder_atr(rows: tuple[DailyBar, ...], period: int = 14) -> list[float | None]:
    tr: list[float] = []
    for idx, row in enumerate(rows):
        if idx == 0:
            tr.append(row.high - row.low)
        else:
            prev_close = rows[idx - 1].close
            tr.append(max(row.high - row.low, abs(row.high - prev_close), abs(row.low - prev_close)))
    out: list[float | None] = [None] * len(rows)
    if not tr:
        return out
    alpha = 1.0 / period
    value = tr[0]
    if period == 1:
        out[0] = value
    for idx in range(1, len(tr)):
        value = alpha * tr[idx] + (1.0 - alpha) * value
        if idx >= period - 1:
            out[idx] = value
    return out


def replay_exact_rule(rows: tuple[DailyBar, ...]) -> tuple[Trade, ...]:
    closes = [row.close for row in rows]
    ema200 = _ema(closes, 200)
    atr14 = _wilder_atr(rows, 14)
    trades: list[Trade] = []
    idx = 0
    while idx < len(rows) - 1:
        ema = ema200[idx]
        atr = atr14[idx]
        if idx < 60 or ema is None or atr is None or not isfinite(atr) or atr <= 0:
            idx += 1
            continue
        ret60 = rows[idx].close / rows[idx - 60].close - 1.0
        direction = 0
        if rows[idx].close > ema and ret60 > 0:
            direction = 1
        elif rows[idx].close < ema and ret60 < 0:
            direction = -1
        if direction == 0:
            idx += 1
            continue

        entry_idx = idx + 1
        entry = rows[entry_idx].open
        risk = 2.0 * atr
        stop = entry - direction * risk
        target = entry + direction * 4.0 * atr
        last_idx = min(len(rows) - 1, entry_idx + 29)
        exit_idx = last_idx
        gross_r: float | None = None
        exit_reason = "TIME"

        for probe in range(entry_idx, last_idx + 1):
            bar = rows[probe]
            if direction > 0:
                stop_hit = bar.low <= stop
                target_hit = bar.high >= target
            else:
                stop_hit = bar.high >= stop
                target_hit = bar.low <= target
            if stop_hit:
                gross_r = -1.0
                exit_idx = probe
                exit_reason = "STOP"
                break
            if target_hit:
                gross_r = 2.0
                exit_idx = probe
                exit_reason = "TARGET"
                break

        if gross_r is None:
            gross_r = direction * (rows[exit_idx].close - entry) / risk

        trades.append(
            Trade(
                signal_day=rows[idx].day,
                entry_day=rows[entry_idx].day,
                exit_day=rows[exit_idx].day,
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                risk_price=risk,
                gross_r=gross_r,
                exit_reason=exit_reason,
            )
        )
        idx = exit_idx + 1
    return tuple(trades)


def _repriced(trades: tuple[Trade, ...], cost_usd: float) -> list[float]:
    return [trade.gross_r - cost_usd / trade.risk_price for trade in trades]


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _bootstrap_positive_fraction(values: list[float], *, trials: int = 100) -> float:
    if not values:
        return 0.0
    rng = Random(SEED)
    positive = 0
    for _ in range(trials):
        sample = [values[rng.randrange(len(values))] for _ in values]
        if sum(sample) > 0:
            positive += 1
    return positive / trials


def summarize(trades: tuple[Trade, ...], *, cost_usd: float) -> Summary:
    values = _repriced(trades, cost_usd)
    if not values:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    pf = gains / losses if losses > 0 else float("inf")
    return Summary(
        trades=len(values),
        net_r=sum(values),
        expectancy_r=sum(values) / len(values),
        profit_factor=pf,
        win_rate=sum(value > 0 for value in values) / len(values),
        max_drawdown_r=_max_drawdown(values),
        bootstrap_positive_fraction_100=_bootstrap_positive_fraction(values),
    )


def filter_entry_period(trades: tuple[Trade, ...], *, start: date, end: date) -> tuple[Trade, ...]:
    return tuple(trade for trade in trades if start <= trade.entry_day <= end)


def crossfeed_pass(primary: Summary, sensitivity: tuple[Summary, ...]) -> bool:
    positive_boundaries = sum(
        item.trades >= 20 and item.expectancy_r > 0 and item.profit_factor > 1.0
        for item in sensitivity
    )
    return bool(
        primary.trades >= 25
        and primary.expectancy_r >= 0.05
        and primary.profit_factor >= 1.10
        and primary.max_drawdown_r <= 20.0
        and primary.bootstrap_positive_fraction_100 >= 0.70
        and positive_boundaries >= 2
    )

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timezone
from math import inf
from statistics import median
from typing import Iterable, Literal

from .models import Bar

UTC = timezone.utc
Direction = Literal["LONG", "SHORT"]
ExitReason = Literal["STOP", "TARGET", "TIME_EXIT"]


@dataclass(frozen=True, slots=True)
class AsiaLondonCandidate:
    name: str
    stop_geometry: Literal["OPPOSITE_RANGE", "MIDPOINT"]
    target_r: float


# Preregistered before broker OOS is read. Do not mutate after observing OOS.
FROZEN_CANDIDATES = (
    AsiaLondonCandidate(
        name="AL_RANGE_1P5R_V2",
        stop_geometry="OPPOSITE_RANGE",
        target_r=1.5,
    ),
    AsiaLondonCandidate(
        name="AL_MIDPOINT_2R_V2",
        stop_geometry="MIDPOINT",
        target_r=2.0,
    ),
)

ASIA_START = time(0, 0)
ASIA_END = time(6, 0)  # exclusive
BREAKOUT_START = time(7, 0)
BREAKOUT_END = time(11, 0)  # exclusive
TIME_EXIT = time(16, 0)
EXPECTED_TIMEFRAME = "M15"


@dataclass(frozen=True, slots=True)
class AsiaLondonTrade:
    symbol: str
    session_date: date
    candidate: str
    direction: Direction
    decision_time: datetime
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    gross_result_r: float
    net_result_r: float
    exit_reason: ExitReason
    exit_time: datetime
    exit_price: float


@dataclass(frozen=True, slots=True)
class ResearchSummary:
    trades: int
    wins: int
    losses: int
    win_rate: float
    average_net_r: float
    median_net_r: float
    profit_factor: float
    total_net_r: float
    max_drawdown_r: float


def pip_size(symbol: str) -> float:
    normalized = str(symbol).upper().replace("/", "").strip()
    return 0.01 if normalized.endswith("JPY") else 0.0001


def _validate_bars(bars: Iterable[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: row.timestamp))
    if not rows:
        return rows
    symbol = rows[0].symbol
    for previous, current in zip(rows, rows[1:]):
        if current.timestamp <= previous.timestamp:
            raise ValueError("bars must have strictly increasing timestamps")
    for row in rows:
        if row.symbol != symbol:
            raise ValueError("replay accepts one symbol at a time")
        if row.timeframe != EXPECTED_TIMEFRAME:
            raise ValueError(f"replay requires {EXPECTED_TIMEFRAME} bars")
        if row.timestamp.tzinfo is None or row.timestamp.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone-aware")
    return rows


def _utc_clock(row: Bar) -> time:
    return row.timestamp.astimezone(UTC).time().replace(tzinfo=None)


def _session_day(row: Bar) -> date:
    return row.timestamp.astimezone(UTC).date()


def _candidate_stop(
    *,
    candidate: AsiaLondonCandidate,
    direction: Direction,
    asia_high: float,
    asia_low: float,
) -> float:
    if candidate.stop_geometry == "OPPOSITE_RANGE":
        return asia_low if direction == "LONG" else asia_high
    midpoint = (asia_high + asia_low) / 2.0
    return midpoint


def _resolve_exit(
    rows: tuple[Bar, ...],
    *,
    direction: Direction,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[float, ExitReason, datetime, float]:
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        raise ValueError("initial risk must be positive")

    last_eligible: Bar | None = None
    for row in rows:
        clock = _utc_clock(row)
        if clock >= TIME_EXIT:
            break
        last_eligible = row
        if direction == "LONG":
            stop_hit = row.low <= stop_loss
            target_hit = row.high >= take_profit
            if stop_hit:
                return -1.0, "STOP", row.timestamp, stop_loss
            if target_hit:
                return (take_profit - entry_price) / risk, "TARGET", row.timestamp, take_profit
        else:
            stop_hit = row.high >= stop_loss
            target_hit = row.low <= take_profit
            if stop_hit:
                return -1.0, "STOP", row.timestamp, stop_loss
            if target_hit:
                return (entry_price - take_profit) / risk, "TARGET", row.timestamp, take_profit

    if last_eligible is None:
        raise ValueError("no post-entry bar exists before time exit")
    if direction == "LONG":
        gross_r = (last_eligible.close - entry_price) / risk
    else:
        gross_r = (entry_price - last_eligible.close) / risk
    return gross_r, "TIME_EXIT", last_eligible.timestamp, last_eligible.close


def replay_candidate(
    bars: Iterable[Bar],
    *,
    candidate: AsiaLondonCandidate,
    round_trip_cost_pips: float,
) -> tuple[AsiaLondonTrade, ...]:
    if candidate.target_r <= 0:
        raise ValueError("target_r must be positive")
    if round_trip_cost_pips < 0:
        raise ValueError("round-trip cost must be non-negative")
    rows = _validate_bars(bars)
    if not rows:
        return ()

    by_day: dict[date, list[Bar]] = defaultdict(list)
    for row in rows:
        by_day[_session_day(row)].append(row)

    output: list[AsiaLondonTrade] = []
    for session_date in sorted(by_day):
        day_rows = tuple(by_day[session_date])
        asia = tuple(
            row
            for row in day_rows
            if ASIA_START <= _utc_clock(row) < ASIA_END
        )
        # A complete six-hour M15 range has 24 bars. Missing bars fail closed.
        if len(asia) != 24:
            continue
        asia_high = max(row.high for row in asia)
        asia_low = min(row.low for row in asia)
        if asia_high <= asia_low:
            continue

        breakout_indices = [
            index
            for index, row in enumerate(day_rows)
            if BREAKOUT_START <= _utc_clock(row) < BREAKOUT_END
            and (row.close > asia_high or row.close < asia_low)
        ]
        if not breakout_indices:
            continue
        decision_index = breakout_indices[0]
        decision_bar = day_rows[decision_index]
        entry_index = decision_index + 1
        if entry_index >= len(day_rows):
            continue
        entry_bar = day_rows[entry_index]
        if _utc_clock(entry_bar) >= TIME_EXIT:
            continue

        direction: Direction = "LONG" if decision_bar.close > asia_high else "SHORT"
        entry_price = float(entry_bar.open)
        stop_loss = _candidate_stop(
            candidate=candidate,
            direction=direction,
            asia_high=asia_high,
            asia_low=asia_low,
        )
        if direction == "LONG" and stop_loss >= entry_price:
            continue
        if direction == "SHORT" and stop_loss <= entry_price:
            continue
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            continue
        take_profit = (
            entry_price + candidate.target_r * risk
            if direction == "LONG"
            else entry_price - candidate.target_r * risk
        )

        post_entry = tuple(day_rows[entry_index:])
        try:
            gross_r, exit_reason, exit_time, exit_price = _resolve_exit(
                post_entry,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        except ValueError:
            continue
        cost_price = round_trip_cost_pips * pip_size(rows[0].symbol)
        net_r = gross_r - cost_price / risk
        output.append(
            AsiaLondonTrade(
                symbol=rows[0].symbol,
                session_date=session_date,
                candidate=candidate.name,
                direction=direction,
                decision_time=decision_bar.timestamp,
                entry_time=entry_bar.timestamp,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                gross_result_r=gross_r,
                net_result_r=net_r,
                exit_reason=exit_reason,
                exit_time=exit_time,
                exit_price=exit_price,
            )
        )
    return tuple(output)


def reprice_cost(
    trades: Iterable[AsiaLondonTrade],
    *,
    round_trip_cost_pips: float,
) -> tuple[AsiaLondonTrade, ...]:
    if round_trip_cost_pips < 0:
        raise ValueError("round-trip cost must be non-negative")
    output: list[AsiaLondonTrade] = []
    for trade in trades:
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk <= 0:
            raise ValueError("initial risk must be positive")
        cost_price = round_trip_cost_pips * pip_size(trade.symbol)
        output.append(
            replace(
                trade,
                net_result_r=trade.gross_result_r - cost_price / risk,
            )
        )
    return tuple(output)


def max_drawdown_r(trades: Iterable[AsiaLondonTrade]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for trade in sorted(trades, key=lambda row: row.entry_time):
        equity += trade.net_result_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summarize(trades: Iterable[AsiaLondonTrade]) -> ResearchSummary:
    rows = tuple(sorted(trades, key=lambda row: row.entry_time))
    if not rows:
        return ResearchSummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    wins = tuple(row.net_result_r for row in rows if row.net_result_r > 0)
    losses = tuple(row.net_result_r for row in rows if row.net_result_r < 0)
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else inf
    values = tuple(row.net_result_r for row in rows)
    return ResearchSummary(
        trades=len(rows),
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(rows),
        average_net_r=sum(values) / len(values),
        median_net_r=median(values),
        profit_factor=profit_factor,
        total_net_r=sum(values),
        max_drawdown_r=max_drawdown_r(rows),
    )


def split_by_calendar(
    trades: Iterable[AsiaLondonTrade],
    *,
    train_end: date,
    validation_end: date,
    oos_end: date,
) -> dict[str, tuple[AsiaLondonTrade, ...]]:
    if not train_end < validation_end < oos_end:
        raise ValueError("calendar split must satisfy train_end < validation_end < oos_end")
    buckets: dict[str, list[AsiaLondonTrade]] = {
        "train": [],
        "validation": [],
        "oos": [],
    }
    for trade in sorted(trades, key=lambda row: row.entry_time):
        if trade.session_date <= train_end:
            buckets["train"].append(trade)
        elif trade.session_date <= validation_end:
            buckets["validation"].append(trade)
        elif trade.session_date <= oos_end:
            buckets["oos"].append(trade)
    return {name: tuple(rows) for name, rows in buckets.items()}


def report_candidate(
    base_trades: Iterable[AsiaLondonTrade],
    *,
    train_end: date,
    validation_end: date,
    oos_end: date,
    base_cost_pips: float,
    stress_cost_pips: float,
) -> dict[str, object]:
    gross = tuple(replace(row, net_result_r=row.gross_result_r) for row in base_trades)
    output: dict[str, object] = {}
    for label, cost in (("base", base_cost_pips), ("stress", stress_cost_pips)):
        priced = reprice_cost(gross, round_trip_cost_pips=cost)
        partitions = split_by_calendar(
            priced,
            train_end=train_end,
            validation_end=validation_end,
            oos_end=oos_end,
        )
        output[label] = {
            "round_trip_cost_pips": cost,
            "periods": {
                name: asdict(summarize(rows))
                for name, rows in partitions.items()
            },
        }
    return output

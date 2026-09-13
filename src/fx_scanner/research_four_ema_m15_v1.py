from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from math import inf

from .demo_four_ema import FOUR_EMA_PERIODS, build_four_ema_features
from .models import Bar
from .technical import atr


@dataclass(frozen=True, slots=True)
class FourEMACandidate:
    name: str
    target_r: float
    atr_stop: float = 1.5
    liquid_session_only: bool = False


# Frozen before validation/OOS is read. The EMA periods are inherited unchanged
# from the existing DEMO shadow reconstruction (9/20/34/50).
FROZEN_CANDIDATES = (
    FourEMACandidate("FOUR_EMA_M15_2R", target_r=2.0),
    FourEMACandidate("FOUR_EMA_M15_2P5R", target_r=2.5),
    FourEMACandidate("FOUR_EMA_M15_LIQUID_2R", target_r=2.0, liquid_session_only=True),
)


@dataclass(frozen=True, slots=True)
class FourEMATrade:
    symbol: str
    candidate: str
    direction: str
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
class FourEMASummary:
    trades: int
    wins: int
    losses: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    total_net_r: float
    max_drawdown_r: float


@dataclass(frozen=True, slots=True)
class _FrameState:
    available: bool
    alignment: str
    long_slopes: bool
    short_slopes: bool
    long_price_side: bool
    short_price_side: bool
    pullback: bool
    spread_state: str


FeatureCache = dict[int, tuple[_FrameState, _FrameState]]


def pip_size(symbol: str) -> float:
    normalized = str(symbol).upper().replace("/", "")
    if normalized in {"XAUUSD", "GOLD"}:
        return 0.01
    return 0.01 if normalized.endswith("JPY") else 0.0001


def _validate_m15(bars: Iterable[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: row.timestamp))
    if not rows:
        return ()
    symbol = rows[0].symbol
    for row in rows:
        if row.symbol != symbol or row.timeframe != "M15":
            raise ValueError("four-EMA replay requires one symbol of M15 bars")
        if row.timestamp.tzinfo is None or row.timestamp.utcoffset() is None:
            raise ValueError("bar timestamps must be timezone-aware")
    if any(b.timestamp <= a.timestamp for a, b in zip(rows, rows[1:])):
        raise ValueError("bars must be strictly increasing")
    return rows


def _resample_h1(m15: tuple[Bar, ...]) -> tuple[Bar, ...]:
    groups: dict[datetime, list[Bar]] = {}
    for row in m15:
        stamp = row.timestamp.replace(minute=0, second=0, microsecond=0)
        groups.setdefault(stamp, []).append(row)
    output: list[Bar] = []
    for stamp in sorted(groups):
        rows = sorted(groups[stamp], key=lambda row: row.timestamp)
        if len(rows) != 4 or [row.timestamp.minute for row in rows] != [0, 15, 30, 45]:
            continue
        output.append(
            Bar(
                symbol=rows[0].symbol,
                timeframe="H1",
                timestamp=stamp,
                open=rows[0].open,
                high=max(row.high for row in rows),
                low=min(row.low for row in rows),
                close=rows[-1].close,
                tick_count=sum(row.tick_count for row in rows),
                spread_avg=sum(row.spread_avg for row in rows) / 4.0,
                spread_max=max(row.spread_max for row in rows),
            )
        )
    return tuple(output)


def _liquid_session(timestamp: datetime) -> bool:
    # UTC approximation shared only by this preregistered research rule.
    return 7 <= timestamp.hour < 17


def _frame_state(rows: tuple[Bar, ...]) -> _FrameState:
    features = build_four_ema_features(
        rows[-120:],
        direction="LONG",
        periods=FOUR_EMA_PERIODS,
    )
    slopes = (
        features.slope_fast_atr,
        features.slope_mid1_atr,
        features.slope_mid2_atr,
        features.slope_slow_atr,
    )
    long_slopes = all(value is not None and value > 0.0 for value in slopes)
    short_slopes = all(value is not None and value < 0.0 for value in slopes)
    latest_close = float(rows[-1].close) if rows else 0.0
    slow = features.ema_slow
    return _FrameState(
        available=features.available,
        alignment=features.alignment,
        long_slopes=long_slopes,
        short_slopes=short_slopes,
        long_price_side=slow is not None and latest_close > slow,
        short_price_side=slow is not None and latest_close < slow,
        pullback=features.pullback_near_fast_cluster,
        spread_state=features.spread_state,
    )


def build_feature_cache(bars: Iterable[Bar]) -> FeatureCache:
    """Compute candidate-independent EMA states once per decision bar.

    This is a runtime optimization only. Each cached state is derived from the
    exact same 120-bar windows and ``build_four_ema_features`` contract used by
    the original preregistered replay.
    """
    rows = _validate_m15(bars)
    if not rows:
        return {}
    h1 = _resample_h1(rows)
    h1_stamps = [row.timestamp for row in h1]
    h1_cache: dict[int, _FrameState] = {}
    output: FeatureCache = {}
    for index in range(120, len(rows) - 1):
        decision = rows[index]
        cutoff = decision.timestamp + timedelta(minutes=15) - timedelta(hours=1)
        h1_end = bisect_right(h1_stamps, cutoff)
        if h1_end < 55:
            continue
        m15_window = rows[max(0, index - 119): index + 1]
        h1_state = h1_cache.get(h1_end)
        if h1_state is None:
            h1_window = h1[max(0, h1_end - 120): h1_end]
            h1_state = _frame_state(tuple(h1_window))
            h1_cache[h1_end] = h1_state
        output[index] = (_frame_state(tuple(m15_window)), h1_state)
    return output


def _aligned(state: _FrameState, direction: str) -> bool:
    if direction == "LONG":
        return bool(
            state.available
            and state.alignment == "BULLISH"
            and state.long_slopes
            and state.long_price_side
        )
    return bool(
        state.available
        and state.alignment == "BEARISH"
        and state.short_slopes
        and state.short_price_side
    )


def replay_candidate(
    bars: Iterable[Bar],
    *,
    candidate: FourEMACandidate,
    max_hold_bars: int = 32,
    feature_cache: FeatureCache | None = None,
) -> tuple[FourEMATrade, ...]:
    rows = _validate_m15(bars)
    if not rows:
        return ()
    cached = feature_cache if feature_cache is not None else build_feature_cache(rows)
    output: list[FourEMATrade] = []
    next_allowed = 120
    previous_pullback = {"LONG": False, "SHORT": False}

    for index in range(120, len(rows) - 1):
        decision = rows[index]
        if index < next_allowed:
            continue
        if candidate.liquid_session_only and not _liquid_session(decision.timestamp):
            continue
        frame_pair = cached.get(index)
        if frame_pair is None:
            continue
        m15_state, h1_state = frame_pair

        signal_direction: str | None = None
        current_pullback = bool(m15_state.pullback)
        for direction in ("LONG", "SHORT"):
            first_touch = current_pullback and not previous_pullback[direction]
            aligned = bool(
                _aligned(m15_state, direction)
                and _aligned(h1_state, direction)
                and h1_state.spread_state in {"STABLE", "EXPANDING"}
            )
            if aligned and first_touch:
                signal_direction = direction
                break

        # The pullback-distance contract is direction-independent. Preserve the
        # original per-direction first-touch state updates exactly.
        previous_pullback["LONG"] = current_pullback
        previous_pullback["SHORT"] = current_pullback
        if signal_direction is None:
            continue

        try:
            atr_value = float(atr(list(rows[max(0, index - 49): index + 1]), 14))
        except Exception:
            continue
        risk = candidate.atr_stop * atr_value
        if risk <= 0:
            continue
        entry_index = index + 1
        entry = rows[entry_index]
        entry_price = float(entry.open)
        if signal_direction == "LONG":
            stop = entry_price - risk
            target = entry_price + candidate.target_r * risk
        else:
            stop = entry_price + risk
            target = entry_price - candidate.target_r * risk

        planned_exit = min(len(rows) - 1, entry_index + max_hold_bars - 1)
        actual_exit = planned_exit
        exit_price = float(rows[planned_exit].close)
        exit_reason = "TIME_EXIT"
        gross_r = (
            (exit_price - entry_price) / risk
            if signal_direction == "LONG"
            else (entry_price - exit_price) / risk
        )
        for probe_index in range(entry_index, planned_exit + 1):
            probe = rows[probe_index]
            if signal_direction == "LONG":
                stop_hit = probe.low <= stop
                target_hit = probe.high >= target
            else:
                stop_hit = probe.high >= stop
                target_hit = probe.low <= target
            # Same conservative ambiguity rule used by validation config.
            if stop_hit:
                gross_r = -1.0
                exit_price = stop
                exit_reason = "STOP"
                actual_exit = probe_index
                break
            if target_hit:
                gross_r = candidate.target_r
                exit_price = target
                exit_reason = "TARGET"
                actual_exit = probe_index
                break

        output.append(
            FourEMATrade(
                symbol=rows[0].symbol,
                candidate=candidate.name,
                direction=signal_direction,
                decision_time=decision.timestamp,
                entry_time=entry.timestamp,
                exit_time=rows[actual_exit].timestamp,
                entry_price=entry_price,
                stop_loss=stop,
                take_profit=target,
                gross_r=float(gross_r),
                net_r=float(gross_r),
                exit_reason=exit_reason,
            )
        )
        next_allowed = actual_exit + 1
    return tuple(output)


def reprice_cost(
    trades: Iterable[FourEMATrade], *, round_trip_cost_pips: float
) -> tuple[FourEMATrade, ...]:
    if round_trip_cost_pips < 0:
        raise ValueError("cost must be non-negative")
    output: list[FourEMATrade] = []
    for trade in trades:
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk <= 0:
            raise ValueError("trade initial risk must be positive")
        cost_r = round_trip_cost_pips * pip_size(trade.symbol) / risk
        output.append(replace(trade, net_r=trade.gross_r - cost_r))
    return tuple(output)


def summarize(trades: Iterable[FourEMATrade]) -> FourEMASummary:
    rows = tuple(sorted(trades, key=lambda row: row.entry_time))
    if not rows:
        return FourEMASummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    wins = [row.net_r for row in rows if row.net_r > 0]
    losses = [row.net_r for row in rows if row.net_r < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    equity = peak = drawdown = 0.0
    for row in rows:
        equity += row.net_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return FourEMASummary(
        trades=len(rows),
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / len(rows),
        expectancy_r=sum(row.net_r for row in rows) / len(rows),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else inf,
        total_net_r=sum(row.net_r for row in rows),
        max_drawdown_r=drawdown,
    )


def split_calendar(
    trades: Iterable[FourEMATrade],
    *,
    train_end: date,
    validation_end: date,
    oos_end: date,
) -> dict[str, tuple[FourEMATrade, ...]]:
    if not train_end < validation_end < oos_end:
        raise ValueError("invalid calendar split")
    result: dict[str, list[FourEMATrade]] = {"train": [], "validation": [], "oos": []}
    for trade in sorted(trades, key=lambda row: row.entry_time):
        day = trade.entry_time.date()
        if day <= train_end:
            result["train"].append(trade)
        elif day <= validation_end:
            result["validation"].append(trade)
        elif day <= oos_end:
            result["oos"].append(trade)
    return {key: tuple(value) for key, value in result.items()}


def summary_payload(trades: Iterable[FourEMATrade]) -> dict[str, object]:
    return asdict(summarize(trades))

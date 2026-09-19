from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ema_smc_reclaim_execution import (
    TP1_R,
    TP2_R,
    build_xau_m15_ema_smc_reclaim_plan,
    evaluate_xau_m15_ema_smc_reclaim_execution,
)
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CANONICAL_REPLAY_V1"
ARTIFACT_CONTRACT = "XAU_CANONICAL_REPLAY_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
PIP_SIZE = 0.01
M15_WINDOW = 240
H1_WINDOW = 60
MAX_HOLD_BARS = 64
BE_BUFFER_R = 0.03


@dataclass(frozen=True, slots=True)
class CanonicalReplaySignal:
    signal_index: int
    direction: str
    signal_at: Any
    score: float
    structural_stop: float
    atr: float
    entry_mode: str | None
    ict_confluence: int
    reason: str


def _validate(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    result = tuple(sorted(rows, key=lambda row: ensure_utc(row.timestamp)))
    if not result:
        raise ValueError("XAU_CANONICAL_REPLAY_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != TIMEFRAME for row in result):
        raise ValueError("XAU_CANONICAL_REPLAY_REQUIRES_XAUUSD_M15")
    return result


def _aggregate_h1(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    buckets: dict[Any, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(row)

    output: list[Bar] = []
    for hour in sorted(buckets):
        group = sorted(buckets[hour], key=lambda row: ensure_utc(row.timestamp))
        minutes = [ensure_utc(row.timestamp).minute for row in group]
        if minutes != [0, 15, 30, 45]:
            continue
        output.append(
            Bar(
                symbol=SYMBOL,
                timeframe="H1",
                timestamp=hour,
                open=float(group[0].open),
                high=max(float(row.high) for row in group),
                low=min(float(row.low) for row in group),
                close=float(group[-1].close),
                tick_count=sum(int(row.tick_count) for row in group),
                spread_avg=sum(float(row.spread_avg) for row in group) / len(group),
                spread_max=max(float(row.spread_max) for row in group),
            )
        )
    return tuple(output)


def _cost_r(*, risk_price: float, bars_held: int, costs: M15ResearchCosts) -> float:
    risk_pips = float(risk_price) / PIP_SIZE
    if risk_pips <= 0.0:
        raise ValueError("XAU_CANONICAL_REPLAY_RISK_INVALID")
    elapsed_days = max(0, int(bars_held)) * 15.0 / (60.0 * 24.0)
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def _trade(
    *,
    rows: Sequence[Bar],
    signal: CanonicalReplaySignal,
    costs: M15ResearchCosts,
    mode: str,
) -> TournamentTrade | None:
    entry_index = signal.signal_index + 1
    if entry_index >= len(rows):
        return None
    entry = float(rows[entry_index].open)
    stop = float(signal.structural_stop)
    risk = entry - stop if signal.direction == "LONG" else stop - entry
    if not isfinite(risk) or risk <= 0.0:
        return None

    target_r = TP1_R if mode == "TP1_FULL" else TP2_R
    target = entry + target_r * risk if signal.direction == "LONG" else entry - target_r * risk
    protected_stop = (
        entry + BE_BUFFER_R * risk
        if signal.direction == "LONG"
        else entry - BE_BUFFER_R * risk
    )
    protected = False
    last_index = min(len(rows) - 1, entry_index + MAX_HOLD_BARS)

    for index in range(entry_index, last_index + 1):
        bar = rows[index]
        active_stop = protected_stop if protected and mode == "CANONICAL_APPROX" else stop
        if signal.direction == "LONG":
            stop_hit = float(bar.low) <= active_stop
            milestone_hit = float(bar.high) >= entry + TP1_R * risk
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= active_stop
            milestone_hit = float(bar.low) <= entry - TP1_R * risk
            target_hit = float(bar.low) <= target

        # Preserve repository conservative convention: a target cannot be
        # credited on the entry candle while the stop can.
        raw_target_hit = target_hit
        if index == entry_index:
            target_hit = False
            milestone_hit = False

        bars_held = index - entry_index
        cost_r = _cost_r(risk_price=risk, bars_held=bars_held, costs=costs)
        if stop_hit:
            gross_r = BE_BUFFER_R if protected and mode == "CANONICAL_APPROX" else -1.0
            return TournamentTrade(
                f"XAU_CANONICAL_{mode}", SYMBOL, signal.direction,
                signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                signal.signal_index, index, entry, active_stop, signal.atr, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held,
                "PROTECTED_STOP" if protected and mode == "CANONICAL_APPROX"
                else ("STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT"),
            )
        if target_hit:
            gross_r = float(target_r)
            return TournamentTrade(
                f"XAU_CANONICAL_{mode}", SYMBOL, signal.direction,
                signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(bar.timestamp),
                signal.signal_index, index, entry, target, signal.atr, stop, target,
                gross_r, cost_r, gross_r - cost_r, bars_held, "TARGET_HIT",
            )
        if mode == "CANONICAL_APPROX" and milestone_hit:
            protected = True

    if last_index < entry_index + MAX_HOLD_BARS:
        return None
    exit_bar = rows[last_index]
    exit_price = float(exit_bar.close)
    gross_r = (
        (exit_price - entry) / risk
        if signal.direction == "LONG"
        else (entry - exit_price) / risk
    )
    cost_r = _cost_r(risk_price=risk, bars_held=MAX_HOLD_BARS, costs=costs)
    return TournamentTrade(
        f"XAU_CANONICAL_{mode}", SYMBOL, signal.direction,
        signal.signal_at, ensure_utc(rows[entry_index].timestamp), ensure_utc(exit_bar.timestamp),
        signal.signal_index, last_index, entry, exit_price, signal.atr, stop, target,
        gross_r, cost_r, gross_r - cost_r, MAX_HOLD_BARS, "TIME_EXIT",
    )


def _split_reasons(reason: str) -> tuple[str, ...]:
    text = str(reason or "UNKNOWN")
    if ":" not in text:
        return (text,)
    prefix, detail = text.split(":", 1)
    parts = tuple(item.strip() for item in detail.split(",") if item.strip())
    return tuple(f"{prefix}:{item}" for item in parts) or (prefix,)


def replay_canonical(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
) -> dict[str, Any]:
    rows = _validate(bars)
    h1 = _aggregate_h1(rows)
    h1_closes = [ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1]

    evaluated = 0
    blockers: Counter[str] = Counter()
    signals: list[CanonicalReplaySignal] = []
    plan_gap_blocks = 0

    for index in range(M15_WINDOW - 1, len(rows) - 1):
        as_of = ensure_utc(rows[index].timestamp) + timedelta(minutes=15)
        h1_count = bisect_right(h1_closes, as_of)
        if h1_count < H1_WINDOW:
            blockers["INSUFFICIENT_H1_HISTORY"] += 1
            continue
        m15_window = rows[index - M15_WINDOW + 1 : index + 1]
        h1_window = h1[max(0, h1_count - H1_WINDOW) : h1_count]
        evaluated += 1
        signal = evaluate_xau_m15_ema_smc_reclaim_execution(
            m15_window,
            h1_window,
            as_of=as_of,
        )
        if not signal.active or not signal.execution_eligible:
            for item in _split_reasons(signal.reason):
                blockers[item] += 1
            continue

        entry = float(rows[index + 1].open)
        try:
            plan = build_xau_m15_ema_smc_reclaim_plan(signal, current_price=entry)
        except ValueError:
            blockers["NEXT_BAR_GAP_GEOMETRY_BLOCK"] += 1
            plan_gap_blocks += 1
            continue
        canonical = dict(signal.canonical_evidence or {})
        ict = dict(signal.ict_evidence or {})
        signals.append(
            CanonicalReplaySignal(
                signal_index=index,
                direction=str(signal.direction),
                signal_at=ensure_utc(rows[index].timestamp),
                score=float(signal.score),
                structural_stop=float(plan.stop_loss),
                atr=float(signal.atr or 0.0),
                entry_mode=canonical.get("entry_mode"),
                ict_confluence=int(ict.get("confluence_count") or 0),
                reason=signal.reason,
            )
        )

    outputs: dict[str, Any] = {}
    for mode in ("TP1_FULL", "TP2_FULL", "CANONICAL_APPROX"):
        base = tuple(
            trade
            for signal in signals
            if (trade := _trade(rows=rows, signal=signal, costs=costs, mode=mode)) is not None
        )
        stressed = tuple(
            trade
            for signal in signals
            if (trade := _trade(rows=rows, signal=signal, costs=stressed_costs, mode=mode)) is not None
        )
        outputs[mode] = {
            "base": compute_metrics(base).payload(),
            "stressed": compute_metrics(stressed).payload(),
            "exit_reasons": dict(Counter(trade.exit_reason for trade in base)),
            "direction": {
                direction: compute_metrics(tuple(trade for trade in base if trade.direction == direction)).payload()
                for direction in ("LONG", "SHORT")
            },
        }

    trading_days = sorted({ensure_utc(row.timestamp).date() for row in rows if ensure_utc(row.timestamp).weekday() < 5})
    signal_days = sorted({ensure_utc(signal.signal_at).date() for signal in signals})
    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "history_bars": len(rows),
        "h1_bars_aggregated": len(h1),
        "evaluated_m15_closes": evaluated,
        "execution_ready_signals": len(signals),
        "next_bar_gap_geometry_blocks": plan_gap_blocks,
        "daily_coverage": {
            "trading_days": len(trading_days),
            "days_with_execution_ready": len(signal_days),
            "signal_day_coverage": (len(signal_days) / len(trading_days)) if trading_days else 0.0,
            "signals_per_signal_day": (len(signals) / len(signal_days)) if signal_days else 0.0,
        },
        "entry_modes": dict(Counter(str(signal.entry_mode or "UNKNOWN") for signal in signals)),
        "ict_confluence": dict(Counter(str(signal.ict_confluence) for signal in signals)),
        "blockers": dict(blockers.most_common()),
        "outcomes": outputs,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "method_note": (
            "Replays the current canonical 240-M15/60-H1 evidence window. H1 bars are "
            "aggregated only from four completed M15 bars. CANONICAL_APPROX moves the "
            "stop to +0.03R after a completed-bar 1.5R milestone and targets 3R; it does "
            "not model the live adverse-structure early exit or >=2R swing trailing."
        ),
    }

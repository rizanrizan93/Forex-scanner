from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .demo_xau_m15_ema_smc_reclaim import (
    MIN_H1_BARS,
    MIN_M15_BARS,
    evaluate_xau_m15_ema_smc_reclaim,
)
from .demo_xau_m15_ema_smc_reclaim_execution import (
    evaluate_xau_m15_ema_smc_reclaim_execution,
)
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CANONICAL_GATE_ATTRIBUTION_V27"
ARTIFACT_CONTRACT = "XAU_CANONICAL_GATE_ATTRIBUTION_V27_EVIDENCE_1"
SYMBOL = "XAUUSD"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True

M15_WINDOW = 240
H1_WINDOW = 60
TARGET_RS = (1.5, 3.0)
MAX_HOLD_BARS = 24
DEVELOPMENT_FRACTION = 0.70

MODE_EXACT_MODEL = "EXACT_MODEL"
MODE_EXACT_FULL = "EXACT_FULL_EXECUTION"
MODE_ORDERED_NO_RETRACE = "ORDERED_NO_RETRACE"
MODE_NO_SWEEP_RETRACE = "STRUCTURE_IMPULSE_RETRACE_NO_SWEEP"
MODES = (
    MODE_EXACT_MODEL,
    MODE_EXACT_FULL,
    MODE_ORDERED_NO_RETRACE,
    MODE_NO_SWEEP_RETRACE,
)


@dataclass(frozen=True, slots=True)
class GateSignal:
    mode: str
    direction: str
    signal_index: int
    signal_at: Any
    score: float
    stop: float
    atr: float


@dataclass(frozen=True, slots=True)
class GateTrade:
    strategy_id: str
    symbol: str
    direction: str
    signal_at: Any
    entry_at: Any
    exit_at: Any
    signal_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    atr: float
    stop_loss: float
    take_profit: float
    gross_r: float
    cost_r: float
    net_r: float
    bars_held: int
    exit_reason: str


def _aggregate_h1(m15: Sequence[Bar]) -> tuple[Bar, ...]:
    buckets: dict[Any, list[Bar]] = {}
    for row in m15:
        stamp = ensure_utc(row.timestamp)
        key = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(row)
    out = []
    for stamp in sorted(buckets):
        group = sorted(buckets[stamp], key=lambda x: ensure_utc(x.timestamp))
        if len(group) != 4:
            continue
        out.append(
            Bar(
                symbol=SYMBOL,
                timeframe="H1",
                timestamp=stamp,
                open=float(group[0].open),
                high=max(float(x.high) for x in group),
                low=min(float(x.low) for x in group),
                close=float(group[-1].close),
                tick_count=sum(int(x.tick_count) for x in group),
                spread_avg=sum(float(x.spread_avg) for x in group) / 4.0,
                spread_max=max(float(x.spread_max) for x in group),
            )
        )
    return tuple(out)


def _assessment(result):
    if result.selected_direction == "LONG":
        return result.long
    if result.selected_direction == "SHORT":
        return result.short
    return None


def _raw_score(assessment) -> float:
    return float(sum(float(v) for v in assessment.components.values()))


def _structural_signal(
    *,
    mode: str,
    result,
    index: int,
    signal_at,
) -> GateSignal | None:
    assessment = _assessment(result)
    if assessment is None:
        return None
    direction = str(assessment.direction)
    evidence = dict(assessment.evidence)
    seq = dict(evidence.get("recent_smc_sequence") or {})
    regime = bool(evidence.get("regime_gate"))
    stop = evidence.get("structural_stop")
    atr = evidence.get("atr14")
    if (
        not regime
        or stop is None
        or atr is None
        or not isfinite(float(stop))
        or not isfinite(float(atr))
        or float(atr) <= 0.0
    ):
        return None

    score = _raw_score(assessment)
    if score < 75.0:
        return None

    if mode == MODE_EXACT_MODEL:
        if not bool(assessment.active) or not bool(evidence.get("structure_gate")):
            return None
        score = float(assessment.score)

    elif mode == MODE_ORDERED_NO_RETRACE:
        if not bool(seq.get("ordered")):
            return None

    elif mode == MODE_NO_SWEEP_RETRACE:
        structure_index = seq.get("mss_index")
        if structure_index is None:
            structure_index = seq.get("bos_index")
        impulse_indexes = [
            x for x in (seq.get("displacement_index"), seq.get("fvg_index"))
            if x is not None
        ]
        impulse_index = max(impulse_indexes) if impulse_indexes else None
        if structure_index is None or impulse_index is None:
            return None
        if abs(int(structure_index) - int(impulse_index)) > 2:
            return None
        event_index = max(int(structure_index), int(impulse_index))
        current_index = M15_WINDOW - 1
        retracement = bool(
            current_index > event_index
            and (bool(seq.get("ema_retrace")) or bool(seq.get("fvg_retrace")))
        )
        if not retracement:
            return None
    else:
        raise ValueError(f"V27_UNKNOWN_MODE:{mode}")

    return GateSignal(
        mode=mode,
        direction=direction,
        signal_index=index,
        signal_at=signal_at,
        score=float(score),
        stop=float(stop),
        atr=float(atr),
    )


def extract_gate_signals(
    rows: Sequence[Bar],
) -> tuple[dict[str, tuple[GateSignal, ...]], dict[str, Any]]:
    m15 = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    h1 = _aggregate_h1(m15)
    h1_close_times = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)

    signals: dict[str, list[GateSignal]] = {mode: [] for mode in MODES}
    stats = {
        "bars_evaluated": 0,
        "regime_gate": 0,
        "structure_gate": 0,
        "ordered": 0,
        "retrace_after_event": 0,
        "ema_or_fvg_retrace": 0,
        "model_watch": 0,
        "model_valid": 0,
        "model_a_plus": 0,
        "full_execution_ready": 0,
        "ict_or_policy_blocked_after_model_valid": 0,
    }

    for i in range(M15_WINDOW - 1, len(m15) - 1):
        signal_close = ensure_utc(m15[i].timestamp) + timedelta(minutes=15)
        h1_count = bisect_right(h1_close_times, signal_close)
        if h1_count < H1_WINDOW:
            continue

        m15_window = m15[i - M15_WINDOW + 1:i + 1]
        h1_window = h1[h1_count - H1_WINDOW:h1_count]
        result = evaluate_xau_m15_ema_smc_reclaim(m15_window, h1_window)
        if not result.available:
            continue
        stats["bars_evaluated"] += 1
        assessment = _assessment(result)
        if assessment is None:
            continue
        evidence = dict(assessment.evidence)
        seq = dict(evidence.get("recent_smc_sequence") or {})
        if bool(evidence.get("regime_gate")):
            stats["regime_gate"] += 1
        if bool(evidence.get("structure_gate")):
            stats["structure_gate"] += 1
        if bool(seq.get("ordered")):
            stats["ordered"] += 1
        if bool(seq.get("retrace_after_event")):
            stats["retrace_after_event"] += 1
        if bool(seq.get("ema_retrace")) or bool(seq.get("fvg_retrace")):
            stats["ema_or_fvg_retrace"] += 1
        if result.state == "WATCH":
            stats["model_watch"] += 1
        elif result.state == "VALID_SETUP":
            stats["model_valid"] += 1
        elif result.state == "A_PLUS_SETUP":
            stats["model_a_plus"] += 1

        signal_at = ensure_utc(m15[i].timestamp)
        for mode in (
            MODE_EXACT_MODEL,
            MODE_ORDERED_NO_RETRACE,
            MODE_NO_SWEEP_RETRACE,
        ):
            signal = _structural_signal(
                mode=mode,
                result=result,
                index=i,
                signal_at=signal_at,
            )
            if signal is not None:
                signals[mode].append(signal)

        exact = signals[MODE_EXACT_MODEL]
        exact_this_bar = bool(exact and exact[-1].signal_index == i)
        if exact_this_bar:
            # Use the next M15 open as the historical as_of. The next bar is not
            # yet closed, matching the runtime decision boundary.
            as_of = ensure_utc(m15[i + 1].timestamp)
            wrapper = evaluate_xau_m15_ema_smc_reclaim_execution(
                m15[i - M15_WINDOW + 1:i + 2],
                h1_window,
                as_of=as_of,
            )
            if wrapper.execution_eligible:
                stats["full_execution_ready"] += 1
                signals[MODE_EXACT_FULL].append(
                    GateSignal(
                        mode=MODE_EXACT_FULL,
                        direction=str(wrapper.direction),
                        signal_index=i,
                        signal_at=signal_at,
                        score=float(wrapper.score),
                        stop=float(wrapper.structural_stop),
                        atr=float(wrapper.atr),
                    )
                )
            else:
                stats["ict_or_policy_blocked_after_model_valid"] += 1

    return (
        {mode: tuple(values) for mode, values in signals.items()},
        stats,
    )


def _cost_r(
    *,
    risk_price: float,
    bars_held: int,
    pip_size: float,
    costs: M15ResearchCosts,
) -> float:
    elapsed_days = max(0, bars_held) * 900.0 / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / (risk_price / pip_size)


def simulate(
    rows: Sequence[Bar],
    *,
    signals: Sequence[GateSignal],
    target_r: float,
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[GateTrade, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    output = []
    next_free_index = 0

    for signal in signals:
        entry_i = signal.signal_index + 1
        if entry_i < next_free_index or entry_i >= len(bars):
            continue
        entry = float(bars[entry_i].open)
        stop = float(signal.stop)
        risk = entry - stop if signal.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0.0:
            continue
        target = (
            entry + float(target_r) * risk
            if signal.direction == "LONG"
            else entry - float(target_r) * risk
        )
        last_i = min(len(bars) - 1, entry_i + MAX_HOLD_BARS)
        exit_i = last_i
        exit_price = float(bars[last_i].close)
        gross_r = None
        reason = "TIME_EXIT"

        for j in range(entry_i, last_i + 1):
            bar = bars[j]
            if signal.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            # Conservative same-bar policy.
            if stop_hit:
                exit_i = j
                exit_price = stop
                gross_r = -1.0
                reason = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                exit_i = j
                exit_price = target
                gross_r = float(target_r)
                reason = "TARGET_HIT"
                break

        if gross_r is None:
            gross_r = (
                (exit_price - entry) / risk
                if signal.direction == "LONG"
                else (entry - exit_price) / risk
            )

        bars_held = exit_i - entry_i
        cost = _cost_r(
            risk_price=risk,
            bars_held=bars_held,
            pip_size=pip_size,
            costs=costs,
        )
        output.append(
            GateTrade(
                strategy_id=f"V27:{signal.mode}:R{target_r:g}",
                symbol=SYMBOL,
                direction=signal.direction,
                signal_at=signal.signal_at,
                entry_at=ensure_utc(bars[entry_i].timestamp),
                exit_at=ensure_utc(bars[exit_i].timestamp),
                signal_index=signal.signal_index,
                exit_index=exit_i,
                entry_price=entry,
                exit_price=exit_price,
                atr=signal.atr,
                stop_loss=stop,
                take_profit=target,
                gross_r=float(gross_r),
                cost_r=float(cost),
                net_r=float(gross_r - cost),
                bars_held=int(bars_held),
                exit_reason=reason,
            )
        )
        next_free_index = exit_i + 1

    return tuple(output)


def _freq(trades: Sequence[GateTrade], dates: Sequence[Any]) -> dict[str, Any]:
    counts = {day: 0 for day in sorted(set(dates))}
    for trade in trades:
        day = ensure_utc(trade.entry_at).date()
        if day in counts:
            counts[day] += 1
    vals = list(counts.values())
    if not vals:
        return {
            "trading_days": 0,
            "trades": 0,
            "mean_trades_per_day": 0.0,
            "median_trades_per_day": 0.0,
            "days_ge_5_fraction": 0.0,
            "zero_trade_days": 0,
            "max_trades_in_day": 0,
        }
    return {
        "trading_days": len(vals),
        "trades": int(sum(vals)),
        "mean_trades_per_day": float(sum(vals) / len(vals)),
        "median_trades_per_day": float(median(vals)),
        "days_ge_5_fraction": float(sum(v >= 5 for v in vals) / len(vals)),
        "zero_trade_days": int(sum(v == 0 for v in vals)),
        "max_trades_in_day": int(max(vals)),
    }


def evaluate_v27(
    rows: Sequence[Bar],
    *,
    pip_size: float,
    base_costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    split = max(
        5_000,
        min(len(bars) - 1, int(len(bars) * DEVELOPMENT_FRACTION)),
    )
    split_time = ensure_utc(bars[split].timestamp)
    signals, gate_stats = extract_gate_signals(bars)

    dev_dates = sorted({
        ensure_utc(x.timestamp).date() for x in bars[:split]
    })
    hold_dates = sorted({
        ensure_utc(x.timestamp).date() for x in bars[split:]
    })

    candidates = []
    for mode in MODES:
        mode_signals = signals[mode]
        for target_r in TARGET_RS:
            base = simulate(
                bars,
                signals=mode_signals,
                target_r=target_r,
                costs=base_costs,
                pip_size=pip_size,
            )
            stress = simulate(
                bars,
                signals=mode_signals,
                target_r=target_r,
                costs=stressed_costs,
                pip_size=pip_size,
            )
            dev_base = tuple(
                t for t in base
                if ensure_utc(t.entry_at) < split_time
                and ensure_utc(t.exit_at) < split_time
            )
            dev_stress = tuple(
                t for t in stress
                if ensure_utc(t.entry_at) < split_time
                and ensure_utc(t.exit_at) < split_time
            )
            hold_base = tuple(
                t for t in base if ensure_utc(t.entry_at) >= split_time
            )
            hold_stress = tuple(
                t for t in stress if ensure_utc(t.entry_at) >= split_time
            )
            candidates.append({
                "mode": mode,
                "target_r": target_r,
                "raw_signals": len(mode_signals),
                "development_base": compute_metrics(dev_base).payload(),
                "development_stressed": compute_metrics(dev_stress).payload(),
                "development_frequency": _freq(dev_base, dev_dates),
                "holdout_base": compute_metrics(hold_base).payload(),
                "holdout_stressed": compute_metrics(hold_stress).payload(),
                "holdout_frequency": _freq(hold_base, hold_dates),
            })

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": SYMBOL,
        "history": {
            "m15_rows": len(bars),
            "start": str(ensure_utc(bars[0].timestamp)),
            "end": str(ensure_utc(bars[-1].timestamp)),
            "split_time": str(split_time),
            "development_fraction": DEVELOPMENT_FRACTION,
        },
        "gate_stats": gate_stats,
        "signal_counts": {mode: len(values) for mode, values in signals.items()},
        "candidates": candidates,
        "note": (
            "Exact canonical model and full execution gates are measured alongside "
            "two one-gate-at-a-time counterfactuals. Counterfactuals are diagnostic "
            "only and cannot alter DEMO authority. All historical output remains "
            "post-hoc because canonical rules and prior XAU evidence are already known."
        ),
    }

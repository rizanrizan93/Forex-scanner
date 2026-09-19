from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
    walk_forward,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_DEVELOPMENT_TRADES,
    MIN_HOLDOUT_TRADES,
    ContinuationSignal,
    _daily_coverage,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_us_reversal_htf_v4 import (
    HtfVariant,
    _aggregate_h1,
    _filtered_signals,
)

RESEARCH_VERSION = "XAU_M5_CONFIRMATION_V6"
ARTIFACT_CONTRACT = "XAU_M5_CONFIRMATION_V6_EVIDENCE_1"
SYMBOL = "XAUUSD"
M5 = "M5"
M15 = "M15"
M5_SECONDS = 5 * 60
PIP_SIZE = 0.01
TRIGGER_LOOKBACK = 3
TRIGGER_WINDOW_BARS = 6
LOCAL_STOP_BUFFER_ATR = 0.20
MAX_HOLD_M5_BARS = 96


@dataclass(frozen=True, slots=True)
class M5Variant:
    variant_id: str
    long_filter: str | None
    long_target_r: float | None
    short_filter: str | None
    short_target_r: float | None
    trigger_mode: str
    stop_mode: str
    selection_eligible: bool = True


VARIANTS = (
    M5Variant(
        "XAU_V6_CONTROL_NOHTF_BASIC_M15STOP_R15",
        "NONE", 1.50, "NONE", 1.50,
        "BASIC_BREAK", "M15",
        selection_eligible=False,
    ),
    M5Variant(
        "XAU_V6_EMA2050NO_BASIC_M15STOP_R15",
        "EMA20_50_NOT_OPPOSED", 1.50,
        "EMA20_50_NOT_OPPOSED", 1.50,
        "BASIC_BREAK", "M15",
    ),
    M5Variant(
        "XAU_V6_EMA2050NO_DISP_M15STOP_R15",
        "EMA20_50_NOT_OPPOSED", 1.50,
        "EMA20_50_NOT_OPPOSED", 1.50,
        "DISPLACEMENT_BREAK", "M15",
    ),
    M5Variant(
        "XAU_V6_HYBRID_BASIC_M15STOP",
        "EMA20_50_NOT_OPPOSED", 1.25,
        "STRUCTURE_MATCH", 1.50,
        "BASIC_BREAK", "M15",
    ),
    M5Variant(
        "XAU_V6_HYBRID_DISP_M15STOP",
        "EMA20_50_NOT_OPPOSED", 1.25,
        "STRUCTURE_MATCH", 1.50,
        "DISPLACEMENT_BREAK", "M15",
    ),
    M5Variant(
        "XAU_V6_HYBRID_BASIC_M5STOP",
        "EMA20_50_NOT_OPPOSED", 1.25,
        "STRUCTURE_MATCH", 1.50,
        "BASIC_BREAK", "M5_LOCAL",
    ),
    M5Variant(
        "XAU_V6_HYBRID_DISP_M5STOP",
        "EMA20_50_NOT_OPPOSED", 1.25,
        "STRUCTURE_MATCH", 1.50,
        "DISPLACEMENT_BREAK", "M5_LOCAL",
    ),
    M5Variant(
        "XAU_V6_LONG125_SHORT200_DISP_M5STOP",
        "EMA20_50_NOT_OPPOSED", 1.25,
        "EMA20_50_NOT_OPPOSED", 2.00,
        "DISPLACEMENT_BREAK", "M5_LOCAL",
    ),
)


def _validate_m5(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    values = tuple(sorted(rows, key=lambda row: ensure_utc(row.timestamp)))
    if not values:
        raise ValueError("XAU_V6_M5_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != M5 for row in values):
        raise ValueError("XAU_V6_REQUIRES_XAUUSD_M5")
    if any(
        ensure_utc(values[index].timestamp) >= ensure_utc(values[index + 1].timestamp)
        for index in range(len(values) - 1)
    ):
        raise ValueError("XAU_V6_M5_NOT_CHRONOLOGICAL")
    return values


def _aggregate_m15(m5: Sequence[Bar]) -> tuple[Bar, ...]:
    buckets: dict[Any, list[Bar]] = {}
    for row in m5:
        stamp = ensure_utc(row.timestamp)
        minute = (stamp.minute // 15) * 15
        key = stamp.replace(minute=minute, second=0, microsecond=0)
        buckets.setdefault(key, []).append(row)

    output: list[Bar] = []
    for stamp in sorted(buckets):
        group = sorted(buckets[stamp], key=lambda row: ensure_utc(row.timestamp))
        expected = [stamp.minute, stamp.minute + 5, stamp.minute + 10]
        if [ensure_utc(row.timestamp).minute for row in group] != expected:
            continue
        output.append(
            Bar(
                symbol=SYMBOL,
                timeframe=M15,
                timestamp=stamp,
                open=float(group[0].open),
                high=max(float(row.high) for row in group),
                low=min(float(row.low) for row in group),
                close=float(group[-1].close),
                tick_count=sum(int(row.tick_count) for row in group),
                spread_avg=sum(float(row.spread_avg) for row in group) / 3.0,
                spread_max=max(float(row.spread_max) for row in group),
            )
        )
    return tuple(output)


def _direction_m15_signals(
    m15: Sequence[Bar],
    *,
    direction: str,
    filter_name: str,
    target_r: float,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
):
    variant = HtfVariant(
        variant_id=f"XAU_V6_POOL_{direction}_{filter_name}_{target_r}",
        htf_filter=filter_name,
        target_r=float(target_r),
        selection_eligible=False,
    )
    signals, evidence = _filtered_signals(
        m15,
        variant=variant,
        h1=h1,
        h1_closes=h1_closes,
        h1_indicators=h1_indicators,
    )
    return tuple(signal for signal in signals if signal.direction == direction), evidence


def _m15_signal_pool(
    m15: Sequence[Bar],
    *,
    variant: M5Variant,
    h1: Sequence[Bar],
    h1_closes,
    h1_indicators,
):
    output = []
    evidence: dict[str, Any] = {}
    if variant.long_filter is not None and variant.long_target_r is not None:
        signals, ev = _direction_m15_signals(
            m15,
            direction="LONG",
            filter_name=variant.long_filter,
            target_r=variant.long_target_r,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        output.extend(signals)
        evidence["LONG"] = ev
    if variant.short_filter is not None and variant.short_target_r is not None:
        signals, ev = _direction_m15_signals(
            m15,
            direction="SHORT",
            filter_name=variant.short_filter,
            target_r=variant.short_target_r,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        output.extend(signals)
        evidence["SHORT"] = ev
    output.sort(key=lambda signal: (ensure_utc(signal.signal_at), signal.direction))
    return tuple(output), evidence


def _us_session(bar: Bar) -> bool:
    hour = ensure_utc(bar.timestamp).hour
    return 12 <= hour < 21


def _m5_confirmed_signal(
    *,
    m5: Sequence[Bar],
    m5_timestamps,
    m5_indicators,
    m15_signal: ContinuationSignal,
    variant: M5Variant,
) -> ContinuationSignal | None:
    m15_close = ensure_utc(m15_signal.signal_at) + timedelta(minutes=15)
    start = bisect_left(m5_timestamps, m15_close)
    last = min(len(m5) - 2, start + TRIGGER_WINDOW_BARS - 1)
    if start < TRIGGER_LOOKBACK or start >= len(m5) - 1:
        return None

    for index in range(start, last + 1):
        row = m5[index]
        if not _us_session(row):
            break
        atr_raw = m5_indicators["atr"][index]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if atr <= 0.0:
            continue
        prior = m5[index - TRIGGER_LOOKBACK:index]
        candle_range = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if candle_range <= 0.0:
            continue

        if m15_signal.direction == "LONG":
            level = max(float(bar.high) for bar in prior)
            broke = float(row.close) > level and float(row.close) > float(row.open)
            close_location = (float(row.close) - float(row.low)) / candle_range
        else:
            level = min(float(bar.low) for bar in prior)
            broke = float(row.close) < level and float(row.close) < float(row.open)
            close_location = (float(row.high) - float(row.close)) / candle_range

        if not broke:
            continue
        if variant.trigger_mode == "DISPLACEMENT_BREAK":
            if body < 0.50 * atr or candle_range < 0.80 * atr or close_location < 0.70:
                continue
        elif variant.trigger_mode != "BASIC_BREAK":
            raise ValueError(f"XAU_V6_TRIGGER_MODE_INVALID:{variant.trigger_mode}")

        stop = float(m15_signal.structural_stop)
        if variant.stop_mode == "M5_LOCAL":
            local_rows = tuple(prior) + (row,)
            if m15_signal.direction == "LONG":
                local_stop = min(float(bar.low) for bar in local_rows) - LOCAL_STOP_BUFFER_ATR * atr
                stop = max(stop, local_stop)
            else:
                local_stop = max(float(bar.high) for bar in local_rows) + LOCAL_STOP_BUFFER_ATR * atr
                stop = min(stop, local_stop)
        elif variant.stop_mode != "M15":
            raise ValueError(f"XAU_V6_STOP_MODE_INVALID:{variant.stop_mode}")

        return ContinuationSignal(
            variant_id=variant.variant_id,
            signal_index=index,
            direction=m15_signal.direction,
            signal_at=ensure_utc(row.timestamp),
            atr=atr,
            breakout_level=float(m15_signal.breakout_level),
            structural_stop=stop,
            reward_r=float(m15_signal.reward_r),
            impulse_index=index,
            retest_index=index,
            fvg_low=None,
            fvg_high=None,
        )
    return None


def _confirmed_signals(
    m5: Sequence[Bar],
    *,
    variant: M5Variant,
    m15_signals: Sequence[ContinuationSignal],
) -> tuple[ContinuationSignal, ...]:
    m5_timestamps = tuple(ensure_utc(row.timestamp) for row in m5)
    indicators = _indicator_series(m5)
    output = []
    seen: set[tuple[Any, str]] = set()
    for signal in m15_signals:
        confirmed = _m5_confirmed_signal(
            m5=m5,
            m5_timestamps=m5_timestamps,
            m5_indicators=indicators,
            m15_signal=signal,
            variant=variant,
        )
        if confirmed is None:
            continue
        key = (ensure_utc(confirmed.signal_at).date(), confirmed.direction)
        if key in seen:
            continue
        seen.add(key)
        output.append(confirmed)
    output.sort(key=lambda signal: (signal.signal_index, signal.direction))
    return tuple(output)


def _roundtrip_cost_r(
    *,
    risk_pips: float,
    bars_held: int,
    costs: M15ResearchCosts,
) -> float:
    if risk_pips <= 0.0:
        raise ValueError("XAU_V6_RISK_PIPS_INVALID")
    elapsed_days = max(0, int(bars_held)) * M5_SECONDS / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def simulate_m5_trades(
    bars: Sequence[Bar],
    *,
    signals: Sequence[ContinuationSignal],
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_m5(bars)
    output: list[TournamentTrade] = []
    for signal in signals:
        entry_index = signal.signal_index + 1
        if entry_index >= len(rows):
            continue
        entry = float(rows[entry_index].open)
        stop = float(signal.structural_stop)
        risk = entry - stop if signal.direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0.0:
            continue
        target = (
            entry + float(signal.reward_r) * risk
            if signal.direction == "LONG"
            else entry - float(signal.reward_r) * risk
        )
        risk_pips = risk / PIP_SIZE
        last_index = min(len(rows) - 1, entry_index + MAX_HOLD_M5_BARS)
        trade = None
        for index in range(entry_index, last_index + 1):
            bar = rows[index]
            if signal.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            raw_target_hit = target_hit
            if index == entry_index:
                target_hit = False
            bars_held = index - entry_index
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=bars_held,
                costs=costs,
            )
            if stop_hit:
                gross_r = -1.0
                trade = TournamentTrade(
                    signal.variant_id,
                    SYMBOL,
                    signal.direction,
                    signal.signal_at,
                    ensure_utc(rows[entry_index].timestamp),
                    ensure_utc(bar.timestamp),
                    signal.signal_index,
                    index,
                    entry,
                    stop,
                    signal.atr,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    bars_held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target_hit else "STOP_HIT",
                )
                break
            if target_hit:
                gross_r = float(signal.reward_r)
                trade = TournamentTrade(
                    signal.variant_id,
                    SYMBOL,
                    signal.direction,
                    signal.signal_at,
                    ensure_utc(rows[entry_index].timestamp),
                    ensure_utc(bar.timestamp),
                    signal.signal_index,
                    index,
                    entry,
                    target,
                    signal.atr,
                    stop,
                    target,
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    bars_held,
                    "TARGET_HIT",
                )
                break

        if trade is None:
            if last_index < entry_index + MAX_HOLD_M5_BARS:
                continue
            exit_bar = rows[last_index]
            exit_price = float(exit_bar.close)
            gross_r = (
                (exit_price - entry) / risk
                if signal.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost_r = _roundtrip_cost_r(
                risk_pips=risk_pips,
                bars_held=MAX_HOLD_M5_BARS,
                costs=costs,
            )
            trade = TournamentTrade(
                signal.variant_id,
                SYMBOL,
                signal.direction,
                signal.signal_at,
                ensure_utc(rows[entry_index].timestamp),
                ensure_utc(exit_bar.timestamp),
                signal.signal_index,
                last_index,
                entry,
                exit_price,
                signal.atr,
                stop,
                target,
                gross_r,
                cost_r,
                gross_r - cost_r,
                MAX_HOLD_M5_BARS,
                "TIME_EXIT",
            )
        output.append(trade)
    return tuple(output)


def _final_oos_pass(metrics: TournamentMetrics) -> bool:
    return bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.win_rate is not None
        and metrics.win_rate >= FINAL_OOS_WIN_RATE_MIN
        and metrics.profit_factor is not None
        and metrics.profit_factor >= FINAL_OOS_PROFIT_FACTOR_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= FINAL_OOS_EXPECTANCY_R_MIN
    )


def evaluate_m5_confirmation_v6(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    m5 = _validate_m5(bars)
    split_index = max(5000, min(len(m5) - 1, int(len(m5) * DEVELOPMENT_FRACTION)))
    development_rows = m5[:split_index]
    holdout_rows = m5[split_index:]
    m15 = _aggregate_m15(m5)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)

    evaluations = []
    base_trade_sets = {}
    stress_trade_sets = {}
    signal_sets = {}

    for variant in VARIANTS:
        m15_signals, filter_evidence = _m15_signal_pool(
            m15,
            variant=variant,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        )
        signals = _confirmed_signals(m5, variant=variant, m15_signals=m15_signals)
        base_trades = simulate_m5_trades(m5, signals=signals, costs=costs)
        stressed_trades = simulate_m5_trades(m5, signals=signals, costs=stressed_costs)
        signal_sets[variant.variant_id] = signals
        base_trade_sets[variant.variant_id] = base_trades
        stress_trade_sets[variant.variant_id] = stressed_trades

        development = tuple(
            trade
            for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade
            for trade in stressed_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(development)
        stressed_metrics = compute_metrics(development_stressed)
        folds, pass_fraction, walk_forward_passed = walk_forward(
            development,
            validation_cfg["walk_forward"],
        )
        stress_passed = _metrics_pass(
            stressed_metrics,
            validation_cfg["stress_acceptance"],
        )
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and walk_forward_passed
            and stress_passed
        )
        development_signals = tuple(
            signal for signal in signals if signal.signal_index < split_index
        )
        direction_metrics = {
            direction: compute_metrics(
                tuple(trade for trade in development if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        evaluations.append(
            {
                "variant": asdict(variant),
                "m15_setup_signals": len(m15_signals),
                "m5_confirmed_signals": len(signals),
                "confirmation_rate": (
                    len(signals) / len(m15_signals) if m15_signals else 0.0
                ),
                "development": metrics.payload(),
                "development_by_direction": direction_metrics,
                "stressed_development": stressed_metrics.payload(),
                "walk_forward": {
                    "folds": [
                        {
                            "fold": fold.fold,
                            "train_trades": fold.train_trades,
                            "test_trades": fold.test_trades,
                            "passed": fold.passed,
                            "test_metrics": fold.test_metrics.payload(),
                        }
                        for fold in folds
                    ],
                    "pass_fraction": pass_fraction,
                    "passed": walk_forward_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "development_coverage": _daily_coverage(
                    development_rows,
                    development_signals,
                ),
                "htf_filter_evidence": filter_evidence,
            }
        )

    eligible = [
        row
        for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
            float(row["development"].get("expectancy_r") or -999.0),
            -float(row["development"].get("max_drawdown_r") or 999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    holdout = None
    promotion_eligible = False
    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        holdout_base = tuple(
            trade
            for trade in base_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(m5)
        )
        holdout_stressed = tuple(
            trade
            for trade in stress_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(m5)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        holdout_signals = tuple(
            signal
            for signal in signal_sets[variant_id]
            if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(holdout_metrics)
            and _metrics_pass(
                holdout_stress_metrics,
                validation_cfg["stress_acceptance"],
            )
        )
        holdout = {
            "variant_id": variant_id,
            "base": holdout_metrics.payload(),
            "stressed": holdout_stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "passed": promotion_eligible,
            "final_oos_thresholds": {
                "minimum_trades": MIN_HOLDOUT_TRADES,
                "win_rate_min": FINAL_OOS_WIN_RATE_MIN,
                "profit_factor_min": FINAL_OOS_PROFIT_FACTOR_MIN,
                "expectancy_r_min": FINAL_OOS_EXPECTANCY_R_MIN,
            },
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": M5,
        "m5_bars": len(m5),
        "m15_bars": len(m15),
        "h1_bars": len(h1),
        "development_bars": len(development_rows),
        "holdout_bars": len(holdout_rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V6 freezes H1-filtered M15 US sweep/reversal plus M5 break/displacement "
            "confirmation before any locked holdout access."
        ),
    }

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
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
from .research_xau_m5_confirmation_v6 import (
    _aggregate_h1,
    _aggregate_m15,
    _validate_m5,
    simulate_m5_trades,
)
from .research_xau_opening_range_fade_v8 import _opening_ranges
from .research_xau_session_liquidity_adaptive_v3 import (
    SESSION_ASIA,
    SESSION_US,
    _session_key,
    _session_name,
)
from .research_xau_us_reversal_htf_v4 import _htf_pass

RESEARCH_VERSION = "XAU_OPENING_RANGE_BREAKOUT_V10"
ARTIFACT_CONTRACT = "XAU_OPENING_RANGE_BREAKOUT_V10_EVIDENCE_1"
SYMBOL = "XAUUSD"
BREAKOUT_BUFFER_ATR = 0.05
BODY_MIN_ATR = 0.40
CLOSE_LOCATION_MIN = 0.70
RETEST_BARS = 6
RETEST_TOLERANCE_ATR = 0.15
STOP_BUFFER_ATR = 0.20
STOP_LOOKBACK = 3


@dataclass(frozen=True, slots=True)
class OrBreakoutVariant:
    variant_id: str
    session: str
    entry_mode: str
    h1_filter: str
    target_r: float
    selection_eligible: bool = True


VARIANTS = (
    OrBreakoutVariant("XAU_V10_US_DIRECT_CONTROL_R15", SESSION_US, "DIRECT", "NONE", 1.50, False),
    OrBreakoutVariant("XAU_V10_US_DIRECT_EMA2050_R125", SESSION_US, "DIRECT", "EMA20_50", 1.25),
    OrBreakoutVariant("XAU_V10_US_DIRECT_EMA2050_R15", SESSION_US, "DIRECT", "EMA20_50", 1.50),
    OrBreakoutVariant("XAU_V10_US_DIRECT_EMA2050_R20", SESSION_US, "DIRECT", "EMA20_50", 2.00),
    OrBreakoutVariant("XAU_V10_US_DIRECT_EMA2050DI_R15", SESSION_US, "DIRECT", "EMA20_50_DI", 1.50),
    OrBreakoutVariant("XAU_V10_US_DIRECT_EMA2050NO_R15", SESSION_US, "DIRECT", "EMA20_50_NOT_OPPOSED", 1.50),
    OrBreakoutVariant("XAU_V10_US_RETEST_EMA2050_R15", SESSION_US, "RETEST", "EMA20_50", 1.50),
    OrBreakoutVariant("XAU_V10_US_RETEST_EMA2050_R20", SESSION_US, "RETEST", "EMA20_50", 2.00),
    OrBreakoutVariant("XAU_V10_ASIA_DIRECT_EMA2050_R15_CONTROL", SESSION_ASIA, "DIRECT", "EMA20_50", 1.50, False),
)


def _htf_ok(
    *,
    signal_close,
    direction: str,
    filter_name: str,
    h1,
    h1_closes,
    h1_indicators,
) -> bool:
    if filter_name == "NONE":
        return True
    count = bisect_right(h1_closes, signal_close)
    if count <= 0:
        return False
    passed, _ = _htf_pass(
        h1=h1,
        h1_indicators=h1_indicators,
        h1_index=count - 1,
        direction=direction,
        filter_name=filter_name,
    )
    return bool(passed)


def _local_stop(rows: Sequence[Bar], index: int, direction: str, atr: float) -> float:
    start = max(0, index - STOP_LOOKBACK + 1)
    recent = rows[start:index + 1]
    if direction == "LONG":
        return min(float(row.low) for row in recent) - STOP_BUFFER_ATR * atr
    return max(float(row.high) for row in recent) + STOP_BUFFER_ATR * atr


def extract_opening_range_breakouts(
    bars: Sequence[Bar],
    *,
    variant: OrBreakoutVariant,
) -> tuple[ContinuationSignal, ...]:
    rows = _validate_m5(bars)
    indicators = _indicator_series(rows)
    m15 = _aggregate_m15(rows)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)
    opening_ranges = _opening_ranges(rows)
    output = []
    seen: set[Any] = set()

    for index in range(max(210, STOP_LOOKBACK), len(rows) - RETEST_BARS - 2):
        row = rows[index]
        session = _session_name(row)
        if session != variant.session:
            continue
        key = _session_key(row, session)
        if key in seen:
            continue
        opening = opening_ranges.get((session, key))
        if opening is None:
            continue
        stamp = ensure_utc(row.timestamp)
        if stamp < opening["close_time"]:
            continue

        atr_raw = indicators["atr"][index]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if atr <= 0.0:
            continue
        candle_range = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if candle_range <= 0.0 or body < BODY_MIN_ATR * atr:
            continue

        upper = float(opening["high"])
        lower = float(opening["low"])
        long_break = bool(
            float(row.close) >= upper + BREAKOUT_BUFFER_ATR * atr
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / candle_range >= CLOSE_LOCATION_MIN
        )
        short_break = bool(
            float(row.close) <= lower - BREAKOUT_BUFFER_ATR * atr
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / candle_range >= CLOSE_LOCATION_MIN
        )
        if long_break == short_break:
            continue
        direction = "LONG" if long_break else "SHORT"
        if not _htf_ok(
            signal_close=stamp + timedelta(minutes=5),
            direction=direction,
            filter_name=variant.h1_filter,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        ):
            continue
        level = upper if direction == "LONG" else lower

        signal_index = index
        if variant.entry_mode == "RETEST":
            found = None
            for j in range(index + 1, min(len(rows) - 1, index + RETEST_BARS + 1)):
                retest = rows[j]
                if _session_name(retest) != session or _session_key(retest, session) != key:
                    break
                accepted = float(retest.close) > level if direction == "LONG" else float(retest.close) < level
                touched = (
                    float(retest.low) <= level + RETEST_TOLERANCE_ATR * atr
                    if direction == "LONG"
                    else float(retest.high) >= level - RETEST_TOLERANCE_ATR * atr
                )
                invalid = (
                    float(retest.close) < level - 0.25 * atr
                    if direction == "LONG"
                    else float(retest.close) > level + 0.25 * atr
                )
                if invalid:
                    break
                if accepted and touched:
                    found = j
                    break
            if found is None:
                continue
            signal_index = found
        elif variant.entry_mode != "DIRECT":
            raise ValueError(f"XAU_V10_ENTRY_MODE_INVALID:{variant.entry_mode}")

        signal_row = rows[signal_index]
        stop = _local_stop(rows, signal_index, direction, atr)
        output.append(
            ContinuationSignal(
                variant_id=variant.variant_id,
                signal_index=signal_index,
                direction=direction,
                signal_at=ensure_utc(signal_row.timestamp),
                atr=atr,
                breakout_level=level,
                structural_stop=stop,
                reward_r=variant.target_r,
                impulse_index=index,
                retest_index=signal_index,
                fvg_low=None,
                fvg_high=None,
            )
        )
        seen.add(key)
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


def evaluate_opening_range_breakout_v10(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_m5(bars)
    split_index = max(5000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]
    evaluations = []
    base_sets = {}
    stress_sets = {}
    signal_sets = {}

    for variant in VARIANTS:
        signals = extract_opening_range_breakouts(rows, variant=variant)
        base = simulate_m5_trades(rows, signals=signals, costs=costs)
        stress = simulate_m5_trades(rows, signals=signals, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress
        signal_sets[variant.variant_id] = signals

        dev = tuple(
            trade for trade in base
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        dev_stress = tuple(
            trade for trade in stress
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(dev, validation_cfg["walk_forward"])
        stress_passed = _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
        dev_signals = tuple(signal for signal in signals if signal.signal_index < split_index)
        by_direction = {
            direction: compute_metrics(
                tuple(trade for trade in dev if trade.direction == direction)
            ).payload()
            for direction in ("LONG", "SHORT")
        }
        evaluations.append(
            {
                "variant": asdict(variant),
                "development": metrics.payload(),
                "development_by_direction": by_direction,
                "stressed_development": stress_metrics.payload(),
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
                    "passed": wf_passed,
                },
                "stress_passed": stress_passed,
                "development_passed": development_passed,
                "development_coverage": _daily_coverage(development_rows, dev_signals),
            }
        )

    eligible = [
        row for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
            float(row["development"].get("expectancy_r") or -999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None
    promotion_eligible = False

    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        base = tuple(
            trade for trade in base_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        stress = tuple(
            trade for trade in stress_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        holdout_signals = tuple(
            signal for signal in signal_sets[variant_id] if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        )
        holdout = {
            "variant_id": variant_id,
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _daily_coverage(holdout_rows, holdout_signals),
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "M5",
        "m5_bars": len(rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
    }

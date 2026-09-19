from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
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
from .research_xau_m5_confirmation_v6 import (
    _aggregate_h1,
    _aggregate_m15,
    _validate_m5,
    simulate_m5_trades,
)
from .research_xau_session_liquidity_adaptive_v3 import (
    SESSION_ASIA,
    SESSION_US,
    _session_key,
    _session_name,
)
from .research_xau_us_reversal_htf_v4 import _htf_pass

RESEARCH_VERSION = "XAU_OPENING_RANGE_FADE_V8"
ARTIFACT_CONTRACT = "XAU_OPENING_RANGE_FADE_V8_EVIDENCE_1"
SYMBOL = "XAUUSD"
OPENING_RANGE_BARS = 12
STOP_BUFFER_ATR = 0.20


@dataclass(frozen=True, slots=True)
class OrFadeVariant:
    variant_id: str
    sessions: tuple[str, ...]
    target_r: float
    h1_filter: str
    sweep_min_atr: float = 0.05
    sweep_max_atr: float = 1.00
    body_min_atr: float = 0.20
    selection_eligible: bool = True


VARIANTS = (
    OrFadeVariant("XAU_V8_US_OR_FADE_R125", (SESSION_US,), 1.25, "NONE"),
    OrFadeVariant("XAU_V8_US_OR_FADE_R15", (SESSION_US,), 1.50, "NONE"),
    OrFadeVariant(
        "XAU_V8_US_OR_FADE_H1NO_R125",
        (SESSION_US,),
        1.25,
        "EMA20_50_NOT_OPPOSED",
    ),
    OrFadeVariant("XAU_V8_ASIA_OR_FADE_R125", (SESSION_ASIA,), 1.25, "NONE"),
    OrFadeVariant(
        "XAU_V8_ASIA_OR_FADE_H1NO_R125",
        (SESSION_ASIA,),
        1.25,
        "EMA20_50_NOT_OPPOSED",
    ),
    OrFadeVariant(
        "XAU_V8_USASIA_OR_FADE_R125",
        (SESSION_US, SESSION_ASIA),
        1.25,
        "NONE",
    ),
    OrFadeVariant(
        "XAU_V8_USASIA_OR_FADE_H1NO_R125",
        (SESSION_US, SESSION_ASIA),
        1.25,
        "EMA20_50_NOT_OPPOSED",
    ),
)


def _session_open_hour(session: str) -> int:
    if session == SESSION_US:
        return 12
    if session == SESSION_ASIA:
        return 22
    raise ValueError(f"XAU_V8_SESSION_INVALID:{session}")


def _opening_ranges(rows: Sequence[Bar]) -> dict[tuple[str, Any], dict[str, Any]]:
    grouped: dict[tuple[str, Any], list[Bar]] = {}
    for row in rows:
        session = _session_name(row)
        if session not in {SESSION_US, SESSION_ASIA}:
            continue
        key = _session_key(row, session)
        grouped.setdefault((session, key), []).append(row)

    output: dict[tuple[str, Any], dict[str, Any]] = {}
    for group_key, values in grouped.items():
        session, _ = group_key
        open_hour = _session_open_hour(session)
        ordered = sorted(values, key=lambda row: ensure_utc(row.timestamp))
        opening = [
            row
            for row in ordered
            if (
                ensure_utc(row.timestamp).hour == open_hour
                and 0 <= ensure_utc(row.timestamp).minute < 60
            )
        ]
        if len(opening) != OPENING_RANGE_BARS:
            continue
        output[group_key] = {
            "high": max(float(row.high) for row in opening),
            "low": min(float(row.low) for row in opening),
            "close_time": ensure_utc(opening[-1].timestamp) + timedelta(minutes=5),
        }
    return output


def _htf_filter_ok(
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


def extract_opening_range_fades(
    bars: Sequence[Bar],
    *,
    variant: OrFadeVariant,
) -> tuple[ContinuationSignal, ...]:
    rows = _validate_m5(bars)
    indicators = _indicator_series(rows)
    m15 = _aggregate_m15(rows)
    h1 = _aggregate_h1(m15)
    h1_closes = tuple(ensure_utc(row.timestamp) + timedelta(hours=1) for row in h1)
    h1_indicators = _indicator_series(h1)
    ranges = _opening_ranges(rows)

    output = []
    seen: set[tuple[str, Any]] = set()

    for index, row in enumerate(rows[:-2]):
        session = _session_name(row)
        if session not in variant.sessions:
            continue
        key = _session_key(row, session)
        if (session, key) in seen:
            continue
        opening = ranges.get((session, key))
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
        if candle_range <= 0.0 or body < variant.body_min_atr * atr:
            continue

        high_excess = (float(row.high) - float(opening["high"])) / atr
        low_excess = (float(opening["low"]) - float(row.low)) / atr
        short_ok = bool(
            variant.sweep_min_atr <= high_excess <= variant.sweep_max_atr
            and float(row.close) < float(opening["high"])
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / candle_range >= 0.55
        )
        long_ok = bool(
            variant.sweep_min_atr <= low_excess <= variant.sweep_max_atr
            and float(row.close) > float(opening["low"])
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / candle_range >= 0.55
        )
        if short_ok == long_ok:
            continue

        direction = "SHORT" if short_ok else "LONG"
        signal_close = stamp + timedelta(minutes=5)
        if not _htf_filter_ok(
            signal_close=signal_close,
            direction=direction,
            filter_name=variant.h1_filter,
            h1=h1,
            h1_closes=h1_closes,
            h1_indicators=h1_indicators,
        ):
            continue

        stop = (
            float(row.high) + STOP_BUFFER_ATR * atr
            if direction == "SHORT"
            else float(row.low) - STOP_BUFFER_ATR * atr
        )
        level = float(opening["high"]) if direction == "SHORT" else float(opening["low"])
        output.append(
            ContinuationSignal(
                variant_id=variant.variant_id,
                signal_index=index,
                direction=direction,
                signal_at=stamp,
                atr=atr,
                breakout_level=level,
                structural_stop=stop,
                reward_r=variant.target_r,
                impulse_index=index,
                retest_index=index,
                fvg_low=None,
                fvg_high=None,
            )
        )
        seen.add((session, key))

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


def evaluate_opening_range_fade_v8(
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
        signals = extract_opening_range_fades(rows, variant=variant)
        base = simulate_m5_trades(rows, signals=signals, costs=costs)
        stress = simulate_m5_trades(rows, signals=signals, costs=stressed_costs)
        signal_sets[variant.variant_id] = signals
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress

        dev = tuple(
            trade
            for trade in base
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        dev_stress = tuple(
            trade
            for trade in stress
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(
            dev,
            validation_cfg["walk_forward"],
        )
        stress_passed = _metrics_pass(
            stress_metrics,
            validation_cfg["stress_acceptance"],
        )
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
        dev_signals = tuple(
            signal for signal in signals if signal.signal_index < split_index
        )
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
                "development_coverage": _daily_coverage(
                    development_rows,
                    dev_signals,
                ),
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
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    holdout = None
    promotion_eligible = False
    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        base = tuple(
            trade
            for trade in base_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        stress = tuple(
            trade
            for trade in stress_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        holdout_signals = tuple(
            signal
            for signal in signal_sets[variant_id]
            if signal.signal_index >= split_index
        )
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(
                stress_metrics,
                validation_cfg["stress_acceptance"],
            )
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

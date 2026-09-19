from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentMetrics, TournamentTrade, compute_metrics, walk_forward
from .demo_xau_m15_canonical_policy import evaluate_canonical_xau_decision
from .demo_xau_m15_ema_smc_reclaim import (
    MIN_H1_BARS,
    MIN_M15_BARS,
    evaluate_xau_m15_ema_smc_reclaim,
)
from .demo_xau_m15_ict_layer import evaluate_ict_execution_context
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
    _validate_bars,
    simulate_trades,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CANONICAL_GATE_V4"
ARTIFACT_CONTRACT = "XAU_CANONICAL_GATE_V4_EVIDENCE_1"
SYMBOL = "XAUUSD"
TIMEFRAME = "M15"
ROLLING_M15_BARS = 640
ROLLING_H1_BARS = 240
SIGNAL_COOLDOWN_BARS = 4
MAX_RISK_ATR = 3.0
MIN_GEOMETRY_RR = 1.0


@dataclass(frozen=True, slots=True)
class CanonicalVariant:
    variant_id: str
    gate: str
    min_score: float
    target_r: float
    min_ict_confluence: int = 0
    require_strict_ict: bool = False
    require_regime_gate: bool = True
    require_structure_gate: bool = True
    require_h1_alignment: bool = False
    selection_eligible: bool = True


# Frozen before V4 locked-holdout access. The first two variants reproduce the
# strict canonical authority but evaluate TP1-like and runner-like reward paths.
# Later variants isolate which gate is suppressing frequency and whether a
# measured relaxation can improve coverage without destroying expectancy.
VARIANTS = (
    CanonicalVariant(
        "XAU_V4_CANONICAL_STRICT_R15",
        "CANONICAL_STRICT",
        75.0,
        1.50,
        min_ict_confluence=2,
        require_strict_ict=True,
    ),
    CanonicalVariant(
        "XAU_V4_CANONICAL_STRICT_R20",
        "CANONICAL_STRICT",
        75.0,
        2.00,
        min_ict_confluence=2,
        require_strict_ict=True,
    ),
    CanonicalVariant(
        "XAU_V4_BASE_SMC75_R15",
        "BASE_SMC",
        75.0,
        1.50,
    ),
    CanonicalVariant(
        "XAU_V4_RELAXED_ICT75_R15",
        "RELAXED_ICT",
        75.0,
        1.50,
        min_ict_confluence=1,
    ),
    CanonicalVariant(
        "XAU_V4_RELAXED_ICT70_R15",
        "RELAXED_ICT",
        70.0,
        1.50,
        min_ict_confluence=1,
    ),
    CanonicalVariant(
        "XAU_V4_H1_STRUCTURE65_R15",
        "H1_STRUCTURE",
        65.0,
        1.50,
        min_ict_confluence=1,
        require_regime_gate=False,
        require_h1_alignment=True,
    ),
    CanonicalVariant(
        "XAU_V4_H1_STRUCTURE65_R20",
        "H1_STRUCTURE",
        65.0,
        2.00,
        min_ict_confluence=1,
        require_regime_gate=False,
        require_h1_alignment=True,
    ),
)


def aggregate_complete_h1(m15_bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = _validate_bars(m15_bars)
    buckets: dict[Any, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(row)

    output: list[Bar] = []
    for hour in sorted(buckets):
        group = sorted(buckets[hour], key=lambda row: ensure_utc(row.timestamp))
        if len(group) != 4:
            continue
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
                spread_avg=sum(float(row.spread_avg) for row in group) / 4.0,
                spread_max=max(float(row.spread_max) for row in group),
            )
        )
    return tuple(output)


def _recent_fvg_overlap(
    rows: Sequence[Bar],
    *,
    index: int,
    direction: str,
    lookback: int = 12,
) -> bool:
    start = max(2, index - lookback + 1)
    latest: tuple[float, float] | None = None
    for cursor in range(start, index + 1):
        left = rows[cursor - 2]
        current = rows[cursor]
        if direction == "LONG" and float(current.low) > float(left.high):
            latest = (float(left.high), float(current.low))
        elif direction == "SHORT" and float(current.high) < float(left.low):
            latest = (float(current.high), float(left.low))
    if latest is None:
        return False
    lo, hi = latest
    current = rows[index]
    return float(current.low) <= hi and float(current.high) >= lo


def _cheap_prefilter(
    rows: Sequence[Bar],
    *,
    index: int,
    indicators: Mapping[str, Sequence[float | None]],
) -> bool:
    atr_raw = indicators["atr"][index]
    adx_raw = indicators["adx"][index]
    ema20_raw = indicators["ema20"][index]
    ema50_raw = indicators["ema50"][index]
    ema200_raw = indicators["ema200"][index]
    if None in (atr_raw, adx_raw, ema20_raw, ema50_raw, ema200_raw):
        return False
    atr_value = float(atr_raw)
    if atr_value <= 0.0 or float(adx_raw) < 12.0:
        return False

    row = rows[index]
    close = float(row.close)
    ema20 = float(ema20_raw)
    ema50 = float(ema50_raw)
    ema200 = float(ema200_raw)
    long_regime = close > ema200 and ema20 >= ema50 - 0.25 * atr_value
    short_regime = close < ema200 and ema20 <= ema50 + 0.25 * atr_value
    if not (long_regime or short_regime):
        return False

    zone_low = min(ema20, ema50) - 0.75 * atr_value
    zone_high = max(ema20, ema50) + 0.75 * atr_value
    ema_near = float(row.low) <= zone_high and float(row.high) >= zone_low
    fvg_near = bool(
        (long_regime and _recent_fvg_overlap(rows, index=index, direction="LONG"))
        or (short_regime and _recent_fvg_overlap(rows, index=index, direction="SHORT"))
    )
    return bool(ema_near or fvg_near)


def _h1_alignment(evidence: Mapping[str, Any], direction: str) -> bool:
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    return bool(
        str(evidence.get("h1_trend") or "").upper() == wanted
        or str(evidence.get("h1_bos") or "").upper() == wanted
        or str(evidence.get("h1_mss_choch") or "").upper() == wanted
    )


def _h1_opposes(evidence: Mapping[str, Any], direction: str) -> bool:
    opposite = "BEARISH" if direction == "LONG" else "BULLISH"
    return str(evidence.get("h1_trend") or "").upper() == opposite


def _relaxed_ict_ok(ict: Mapping[str, Any], *, min_confluence: int) -> bool:
    if not bool(ict.get("available")):
        return False
    if not bool(ict.get("anti_chase_ok")):
        return False
    external_target = ict.get("external_liquidity_target")
    if external_target is None:
        return False
    location_ok = bool(ict.get("premium_discount_ok") or ict.get("ote_retest"))
    if not location_ok:
        return False
    return int(ict.get("confluence_count") or 0) >= int(min_confluence)


def _geometry_ok(
    *,
    direction: str,
    close: float,
    evidence: Mapping[str, Any],
    ict: Mapping[str, Any],
) -> bool:
    atr_value = evidence.get("atr14")
    stop_value = evidence.get("structural_stop")
    if atr_value is None or stop_value is None:
        return False
    atr_value = float(atr_value)
    stop_value = float(stop_value)
    if not all(isfinite(value) for value in (atr_value, stop_value, close)) or atr_value <= 0.0:
        return False
    risk = close - stop_value if direction == "LONG" else stop_value - close
    if risk <= 0.0 or risk / atr_value > MAX_RISK_ATR:
        return False

    target = ict.get("external_liquidity_target")
    if target is None:
        target = evidence.get("liquidity_target")
    if target is None:
        return False
    target = float(target)
    reward = target - close if direction == "LONG" else close - target
    return reward > 0.0 and reward / risk >= MIN_GEOMETRY_RR


def _variant_passes(
    variant: CanonicalVariant,
    *,
    selected,
    ict_payload: Mapping[str, Any],
    canonical,
) -> bool:
    if selected is None or selected.direction not in {"LONG", "SHORT"}:
        return False
    direction = selected.direction
    evidence = dict(selected.evidence)
    if float(selected.score) < float(variant.min_score):
        return False
    if variant.require_regime_gate and not bool(evidence.get("regime_gate")):
        return False
    if variant.require_structure_gate and not bool(evidence.get("structure_gate")):
        return False
    if _h1_opposes(evidence, direction):
        return False

    adx = evidence.get("adx14")
    if adx is None or float(adx) < 15.0:
        return False
    if not bool(evidence.get("directional_di")):
        return False
    if variant.require_h1_alignment and not _h1_alignment(evidence, direction):
        return False

    if variant.gate == "CANONICAL_STRICT":
        if not bool(getattr(selected, "active", False)):
            return False
        if not bool(ict_payload.get("execution_ready")):
            return False
        if int(ict_payload.get("confluence_count") or 0) < variant.min_ict_confluence:
            return False
        if not bool(canonical.execution_ready):
            return False
    elif variant.gate == "BASE_SMC":
        if not bool(getattr(selected, "active", False)):
            return False
    elif variant.gate in {"RELAXED_ICT", "H1_STRUCTURE"}:
        if not _relaxed_ict_ok(
            ict_payload,
            min_confluence=variant.min_ict_confluence,
        ):
            return False
    else:
        raise ValueError(f"XAU_V4_GATE_INVALID:{variant.gate}")

    return _geometry_ok(
        direction=direction,
        close=float(evidence.get("price") or 0.0),
        evidence=evidence,
        ict=ict_payload,
    )


def extract_canonical_gate_signals(
    bars: Sequence[Bar],
) -> tuple[dict[str, tuple[ContinuationSignal, ...]], dict[str, Any]]:
    rows = _validate_bars(bars)
    h1_rows = aggregate_complete_h1(rows)
    h1_close_times = [
        ensure_utc(row.timestamp) + timedelta(hours=1)
        for row in h1_rows
    ]
    indicators = _indicator_series(rows)
    output: dict[str, list[ContinuationSignal]] = {
        variant.variant_id: [] for variant in VARIANTS
    }
    last_signal_index = {variant.variant_id: -10_000 for variant in VARIANTS}

    minimum_index = max(ROLLING_M15_BARS, MIN_M15_BARS + 5)
    candidate_bars = 0
    exact_evaluations = 0
    directional_evaluations = 0

    for index in range(minimum_index, len(rows) - 2):
        if not _cheap_prefilter(rows, index=index, indicators=indicators):
            continue
        candidate_bars += 1

        as_of = ensure_utc(rows[index].timestamp) + timedelta(minutes=15)
        h1_end = bisect_right(h1_close_times, as_of)
        if h1_end < MIN_H1_BARS:
            continue
        h1_window = h1_rows[max(0, h1_end - ROLLING_H1_BARS):h1_end]
        m15_window = rows[max(0, index - ROLLING_M15_BARS + 1):index + 1]
        if len(m15_window) < MIN_M15_BARS:
            continue

        result = evaluate_xau_m15_ema_smc_reclaim(m15_window, h1_window)
        exact_evaluations += 1
        direction = result.selected_direction
        selected = result.long if direction == "LONG" else result.short if direction == "SHORT" else None
        if selected is None or direction not in {"LONG", "SHORT"}:
            continue
        directional_evaluations += 1

        evidence = dict(selected.evidence)
        atr_value = evidence.get("atr14")
        stop_value = evidence.get("structural_stop")
        if atr_value is None or stop_value is None:
            continue
        atr_value = float(atr_value)
        stop_value = float(stop_value)
        if atr_value <= 0.0:
            continue

        ict = evaluate_ict_execution_context(
            m15_window,
            direction=direction,
            atr_value=atr_value,
            as_of=as_of,
        )
        ict_payload = ict.to_payload()
        canonical = evaluate_canonical_xau_decision(
            direction=direction,
            score=float(selected.score),
            evidence=evidence,
            ict_evidence=ict_payload,
        )

        for variant in VARIANTS:
            if index - last_signal_index[variant.variant_id] < SIGNAL_COOLDOWN_BARS:
                continue
            if not _variant_passes(
                variant,
                selected=selected,
                ict_payload=ict_payload,
                canonical=canonical,
            ):
                continue
            output[variant.variant_id].append(
                ContinuationSignal(
                    variant_id=variant.variant_id,
                    signal_index=index,
                    direction=direction,
                    signal_at=ensure_utc(rows[index].timestamp),
                    atr=atr_value,
                    breakout_level=float(evidence.get("price") or rows[index].close),
                    structural_stop=stop_value,
                    reward_r=float(variant.target_r),
                    impulse_index=index,
                    retest_index=index,
                    fvg_low=None,
                    fvg_high=None,
                )
            )
            last_signal_index[variant.variant_id] = index

    diagnostics = {
        "history_bars": len(rows),
        "complete_h1_bars": len(h1_rows),
        "prefilter_candidate_bars": candidate_bars,
        "exact_model_evaluations": exact_evaluations,
        "directional_evaluations": directional_evaluations,
        "rolling_m15_bars": ROLLING_M15_BARS,
        "rolling_h1_bars": ROLLING_H1_BARS,
        "signal_cooldown_bars": SIGNAL_COOLDOWN_BARS,
        "method_note": (
            "The production EMA/SMC, ICT and canonical-policy evaluators are reused "
            "on rolling closed-bar windows. A permissive no-lookahead prefilter "
            "reduces compute; final eligibility is always decided by exact model "
            "evidence. H1 bars are aggregated only from four completed M15 bars."
        ),
    }
    return {key: tuple(value) for key, value in output.items()}, diagnostics


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


def evaluate_canonical_gate_v4(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    signals_by_variant, diagnostics = extract_canonical_gate_signals(rows)
    split_index = max(1000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    development_rows = rows[:split_index]
    holdout_rows = rows[split_index:]

    evaluations: list[dict[str, Any]] = []
    base_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}
    stress_trade_sets: dict[str, tuple[TournamentTrade, ...]] = {}

    for variant in VARIANTS:
        signals = signals_by_variant[variant.variant_id]
        base_trades = simulate_trades(rows, signals=signals, costs=costs)
        stress_trades = simulate_trades(rows, signals=signals, costs=stressed_costs)
        base_trade_sets[variant.variant_id] = base_trades
        stress_trade_sets[variant.variant_id] = stress_trades

        development = tuple(
            trade for trade in base_trades
            if trade.signal_index < split_index and trade.exit_index < split_index
        )
        development_stressed = tuple(
            trade for trade in stress_trades
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
        evaluations.append(
            {
                "variant": asdict(variant),
                "signals_total": len(signals),
                "development": metrics.payload(),
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
            -float(row["development"].get("max_drawdown_r") or 999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None

    holdout: dict[str, Any] | None = None
    promotion_eligible = False
    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        holdout_base = tuple(
            trade for trade in base_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_stressed = tuple(
            trade for trade in stress_trade_sets[variant_id]
            if trade.signal_index >= split_index and trade.exit_index < len(rows)
        )
        holdout_metrics = compute_metrics(holdout_base)
        holdout_stress_metrics = compute_metrics(holdout_stressed)
        holdout_signals = tuple(
            signal for signal in signals_by_variant[variant_id]
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
            "final_oos_thresholds": {
                "minimum_trades": MIN_HOLDOUT_TRADES,
                "win_rate_min": FINAL_OOS_WIN_RATE_MIN,
                "profit_factor_min": FINAL_OOS_PROFIT_FACTOR_MIN,
                "expectancy_r_min": FINAL_OOS_EXPECTANCY_R_MIN,
            },
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "history_bars": len(rows),
        "development_bars": len(development_rows),
        "holdout_bars": len(holdout_rows),
        "diagnostics": diagnostics,
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V4 directly reuses production EMA/SMC, ICT and canonical policy on "
            "closed-bar rolling windows. Gate relaxations were preregistered before "
            "locked-holdout access. No V4 variant can change broker authority."
        ),
    }

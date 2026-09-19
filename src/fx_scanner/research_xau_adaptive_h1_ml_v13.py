from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import date
from math import cos, isfinite, pi, sin
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
)
from .models import Bar, ensure_utc
from .research_xau_d1_tsmom_crossfeed_v1 import _ema, resample_h1_to_daily
from .research_xau_m15_continuation_tournament import (
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_HOLDOUT_TRADES,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_ADAPTIVE_H1_ML_V13"
ARTIFACT_CONTRACT = "XAU_ADAPTIVE_H1_ML_V13_EVIDENCE_1"
SYMBOL = "XAUUSD"
PIP_SIZE = 0.01
H1_SECONDS = 3600
CHECKPOINT_HOURS = (0, 7, 12, 15, 22)
STOP_ATR = 1.0
TARGET_R = 1.25
MAX_HOLD_BARS = 6
PURGE_DAYS = 2
POLICY_MARGIN_R = 0.05
THRESHOLDS_R = (0.05, 0.10, 0.15, 0.20)
MIN_DEVELOPMENT_TRADES = 130
MODEL_RANDOM_STATE = 260919


@dataclass(frozen=True, slots=True)
class CandidateEvent:
    day: date
    entry_index: int
    entry_hour: int
    features: tuple[float, ...]
    base_long: TournamentTrade
    base_short: TournamentTrade
    stress_long: TournamentTrade
    stress_short: TournamentTrade


@dataclass(frozen=True, slots=True)
class ThresholdEvaluation:
    threshold_r: float
    base_metrics: TournamentMetrics
    stressed_metrics: TournamentMetrics
    fold_pass_fraction: float
    fold_rows: tuple[dict[str, Any], ...]
    coverage: float
    development_passed: bool


def _validate_h1(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if not rows:
        raise ValueError("XAU_V13_H1_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != "H1" for row in rows):
        raise ValueError("XAU_V13_REQUIRES_XAUUSD_H1")
    return rows


def _cost_r(*, risk_pips: float, bars_held: int, costs: M15ResearchCosts) -> float:
    elapsed_days = max(0, bars_held) * H1_SECONDS / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def _action_trade(
    rows: Sequence[Bar],
    *,
    entry_index: int,
    direction: str,
    atr: float,
    costs: M15ResearchCosts,
) -> TournamentTrade | None:
    if entry_index + 1 >= len(rows):
        return None
    entry_bar = rows[entry_index]
    entry = float(entry_bar.open)
    risk = STOP_ATR * atr
    if not isfinite(risk) or risk <= 0:
        return None
    stop = entry - risk if direction == "LONG" else entry + risk
    target = entry + TARGET_R * risk if direction == "LONG" else entry - TARGET_R * risk
    risk_pips = risk / PIP_SIZE
    last = min(len(rows) - 1, entry_index + MAX_HOLD_BARS - 1)

    for idx in range(entry_index, last + 1):
        bar = rows[idx]
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target
        bars_held = idx - entry_index + 1
        cost_r = _cost_r(risk_pips=risk_pips, bars_held=bars_held, costs=costs)
        if stop_hit:
            gross_r = -1.0
            return TournamentTrade(
                RESEARCH_VERSION,
                SYMBOL,
                direction,
                ensure_utc(rows[entry_index - 1].timestamp),
                ensure_utc(entry_bar.timestamp),
                ensure_utc(bar.timestamp),
                entry_index - 1,
                idx,
                entry,
                stop,
                atr,
                stop,
                target,
                gross_r,
                cost_r,
                gross_r - cost_r,
                bars_held,
                "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT",
            )
        if target_hit:
            gross_r = TARGET_R
            return TournamentTrade(
                RESEARCH_VERSION,
                SYMBOL,
                direction,
                ensure_utc(rows[entry_index - 1].timestamp),
                ensure_utc(entry_bar.timestamp),
                ensure_utc(bar.timestamp),
                entry_index - 1,
                idx,
                entry,
                target,
                atr,
                stop,
                target,
                gross_r,
                cost_r,
                gross_r - cost_r,
                bars_held,
                "TARGET_HIT",
            )

    exit_bar = rows[last]
    exit_price = float(exit_bar.close)
    gross_r = (
        (exit_price - entry) / risk
        if direction == "LONG"
        else (entry - exit_price) / risk
    )
    bars_held = last - entry_index + 1
    cost_r = _cost_r(risk_pips=risk_pips, bars_held=bars_held, costs=costs)
    return TournamentTrade(
        RESEARCH_VERSION,
        SYMBOL,
        direction,
        ensure_utc(rows[entry_index - 1].timestamp),
        ensure_utc(entry_bar.timestamp),
        ensure_utc(exit_bar.timestamp),
        entry_index - 1,
        last,
        entry,
        exit_price,
        atr,
        stop,
        target,
        gross_r,
        cost_r,
        gross_r - cost_r,
        bars_held,
        "TIME_EXIT",
    )


def _daily_context(rows: Sequence[Bar]):
    daily = resample_h1_to_daily(tuple(rows), boundary_hour_utc=0)
    days = [row.day for row in daily]
    closes = [float(row.close) for row in daily]
    ema200 = _ema(closes, 200)
    return daily, days, ema200


def _candidate_features(
    rows: Sequence[Bar],
    indicators,
    *,
    entry_index: int,
    daily,
    daily_days,
    daily_ema200,
) -> tuple[float, ...] | None:
    prev = entry_index - 1
    if prev < 220:
        return None
    atr_raw = indicators["atr"][prev]
    ema20_raw = indicators["ema20"][prev]
    ema50_raw = indicators["ema50"][prev]
    ema200_raw = indicators["ema200"][prev]
    adx_raw = indicators["adx"][prev]
    plus_raw = indicators["plus_di"][prev]
    minus_raw = indicators["minus_di"][prev]
    if None in (atr_raw, ema20_raw, ema50_raw, ema200_raw, adx_raw, plus_raw, minus_raw):
        return None
    atr = float(atr_raw)
    if not isfinite(atr) or atr <= 0:
        return None

    stamp = ensure_utc(rows[entry_index].timestamp)
    d_idx = bisect_left(daily_days, stamp.date()) - 1
    if d_idx < 199 or d_idx < 60:
        return None
    d_ema = daily_ema200[d_idx]
    if d_ema is None:
        return None
    d_close = float(daily[d_idx].close)
    d_prior = float(daily[d_idx - 60].close)
    if d_prior <= 0 or d_close <= 0:
        return None
    d_ret60 = d_close / d_prior - 1.0
    d_dist_ema = (d_close - float(d_ema)) / d_close
    d_bias = 1.0 if d_dist_ema > 0 and d_ret60 > 0 else -1.0 if d_dist_ema < 0 and d_ret60 < 0 else 0.0

    close = float(rows[prev].close)
    ema20 = float(ema20_raw)
    ema50 = float(ema50_raw)
    ema200 = float(ema200_raw)
    high = float(rows[prev].high)
    low = float(rows[prev].low)
    open_ = float(rows[prev].open)
    candle_range = max(high - low, 1e-12)
    body_signed = (close - open_) / atr
    close_loc = (close - low) / candle_range

    def delta(back: int) -> float:
        return (close - float(rows[prev - back].close)) / atr

    prev_day = daily[d_idx]
    hour_angle = 2.0 * pi * stamp.hour / 24.0
    weekday_angle = 2.0 * pi * stamp.weekday() / 7.0
    values = (
        d_bias,
        d_ret60,
        d_dist_ema,
        (close - ema20) / atr,
        (ema20 - ema50) / atr,
        (ema50 - ema200) / atr,
        float(adx_raw) / 100.0,
        (float(plus_raw) - float(minus_raw)) / 100.0,
        delta(1),
        delta(3),
        delta(6),
        delta(12),
        delta(24),
        body_signed,
        candle_range / atr,
        close_loc,
        (close - float(prev_day.high)) / atr,
        (close - float(prev_day.low)) / atr,
        sin(hour_angle),
        cos(hour_angle),
        sin(weekday_angle),
        cos(weekday_angle),
    )
    if not all(isfinite(float(value)) for value in values):
        return None
    return tuple(float(value) for value in values)


def build_candidate_events(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
) -> tuple[CandidateEvent, ...]:
    rows = _validate_h1(bars)
    indicators = _indicator_series(rows)
    daily, daily_days, daily_ema200 = _daily_context(rows)
    events: list[CandidateEvent] = []
    for entry_index in range(221, len(rows) - MAX_HOLD_BARS):
        stamp = ensure_utc(rows[entry_index].timestamp)
        if stamp.minute != 0 or stamp.hour not in CHECKPOINT_HOURS:
            continue
        features = _candidate_features(
            rows,
            indicators,
            entry_index=entry_index,
            daily=daily,
            daily_days=daily_days,
            daily_ema200=daily_ema200,
        )
        if features is None:
            continue
        atr = float(indicators["atr"][entry_index - 1])
        base_long = _action_trade(rows, entry_index=entry_index, direction="LONG", atr=atr, costs=costs)
        base_short = _action_trade(rows, entry_index=entry_index, direction="SHORT", atr=atr, costs=costs)
        stress_long = _action_trade(rows, entry_index=entry_index, direction="LONG", atr=atr, costs=stressed_costs)
        stress_short = _action_trade(rows, entry_index=entry_index, direction="SHORT", atr=atr, costs=stressed_costs)
        if None in (base_long, base_short, stress_long, stress_short):
            continue
        events.append(
            CandidateEvent(
                day=stamp.date(),
                entry_index=entry_index,
                entry_hour=stamp.hour,
                features=features,
                base_long=base_long,
                base_short=base_short,
                stress_long=stress_long,
                stress_short=stress_short,
            )
        )
    return tuple(events)


def _fit_model(events: Sequence[CandidateEvent]):
    try:
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor
    except Exception as exc:
        raise RuntimeError("XAU_V13_REQUIRES_NUMPY_SKLEARN") from exc

    x_rows = []
    y_rows = []
    for event in events:
        x_rows.append((*event.features, 1.0))
        y_rows.append(float(event.base_long.net_r))
        x_rows.append((*event.features, -1.0))
        y_rows.append(float(event.base_short.net_r))
    if len(x_rows) < 200:
        raise ValueError("XAU_V13_TRAINING_SAMPLE_TOO_SMALL")
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=160,
        max_leaf_nodes=15,
        min_samples_leaf=50,
        l2_regularization=2.0,
        random_state=MODEL_RANDOM_STATE,
    )
    model.fit(np.asarray(x_rows, dtype=float), np.asarray(y_rows, dtype=float))
    return model


def _select_policy_trades(
    model,
    events: Sequence[CandidateEvent],
    *,
    threshold_r: float,
    stressed: bool,
) -> tuple[TournamentTrade, ...]:
    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError("XAU_V13_REQUIRES_NUMPY") from exc

    by_day: dict[date, list[CandidateEvent]] = {}
    for event in events:
        by_day.setdefault(event.day, []).append(event)
    selected: list[TournamentTrade] = []
    for day in sorted(by_day):
        for event in sorted(by_day[day], key=lambda row: row.entry_index):
            x = np.asarray([
                (*event.features, 1.0),
                (*event.features, -1.0),
            ], dtype=float)
            pred_long, pred_short = (float(v) for v in model.predict(x))
            best = max(pred_long, pred_short)
            if best < float(threshold_r) or abs(pred_long - pred_short) < POLICY_MARGIN_R:
                continue
            if pred_long > pred_short:
                selected.append(event.stress_long if stressed else event.base_long)
            else:
                selected.append(event.stress_short if stressed else event.base_short)
            break
    return tuple(selected)


def _coverage(events: Sequence[CandidateEvent], trades: Sequence[TournamentTrade]) -> float:
    days = {event.day for event in events}
    trade_days = {ensure_utc(trade.entry_at).date() for trade in trades}
    return len(trade_days) / len(days) if days else 0.0


def _fold_pass(metrics: TournamentMetrics, cfg: Mapping[str, Any]) -> bool:
    return bool(
        metrics.completed_trades >= int(cfg["minimum_test_trades"])
        and metrics.win_rate is not None
        and metrics.win_rate >= float(cfg["fold_win_rate_min"])
        and metrics.profit_factor is not None
        and metrics.profit_factor >= float(cfg["fold_profit_factor_min"])
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= float(cfg["fold_expectancy_r_min"])
    )


def _evaluate_threshold_wfo(
    events: Sequence[CandidateEvent],
    *,
    threshold_r: float,
    validation_cfg: Mapping[str, Any],
) -> ThresholdEvaluation:
    all_days = sorted({event.day for event in events})
    prehold_end = int(len(all_days) * 0.80)
    prehold_days = all_days[:prehold_end]
    fold_bounds = ((0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80))
    all_base: list[TournamentTrade] = []
    all_stress: list[TournamentTrade] = []
    fold_rows: list[dict[str, Any]] = []
    passed = 0

    for fold_no, (train_fraction, test_fraction) in enumerate(fold_bounds, start=1):
        test_start = int(len(all_days) * train_fraction)
        test_end = int(len(all_days) * test_fraction)
        train_end = max(0, test_start - PURGE_DAYS)
        train_days = set(all_days[:train_end])
        test_days = set(all_days[test_start:test_end])
        train_events = tuple(event for event in events if event.day in train_days)
        test_events = tuple(event for event in events if event.day in test_days)
        if not train_events or not test_events:
            continue
        model = _fit_model(train_events)
        base = _select_policy_trades(
            model,
            test_events,
            threshold_r=threshold_r,
            stressed=False,
        )
        stress = _select_policy_trades(
            model,
            test_events,
            threshold_r=threshold_r,
            stressed=True,
        )
        metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        fold_ok = _fold_pass(metrics, validation_cfg["walk_forward"])
        passed += int(fold_ok)
        all_base.extend(base)
        all_stress.extend(stress)
        fold_rows.append({
            "fold": fold_no,
            "train_days": len(train_days),
            "test_days": len(test_days),
            "trades": metrics.completed_trades,
            "base": metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _coverage(test_events, base),
            "passed": fold_ok,
        })

    base_metrics = compute_metrics(tuple(all_base))
    stress_metrics = compute_metrics(tuple(all_stress))
    pass_fraction = passed / len(fold_rows) if fold_rows else 0.0
    development_passed = bool(
        base_metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
        and pass_fraction >= float(validation_cfg["walk_forward"]["minimum_pass_fraction"])
        and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
    )
    prehold_events = tuple(event for event in events if event.day in set(prehold_days))
    return ThresholdEvaluation(
        threshold_r=threshold_r,
        base_metrics=base_metrics,
        stressed_metrics=stress_metrics,
        fold_pass_fraction=pass_fraction,
        fold_rows=tuple(fold_rows),
        coverage=_coverage(prehold_events, tuple(all_base)),
        development_passed=development_passed,
    )


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


def evaluate_adaptive_h1_ml_v13(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_h1(bars)
    events = build_candidate_events(
        rows,
        costs=costs,
        stressed_costs=stressed_costs,
    )
    evaluations = tuple(
        _evaluate_threshold_wfo(
            events,
            threshold_r=threshold,
            validation_cfg=validation_cfg,
        )
        for threshold in THRESHOLDS_R
    )
    eligible = [row for row in evaluations if row.development_passed]
    eligible.sort(
        key=lambda row: (
            row.fold_pass_fraction,
            row.stressed_metrics.expectancy_r if row.stressed_metrics.expectancy_r is not None else -999.0,
            row.stressed_metrics.profit_factor if row.stressed_metrics.profit_factor is not None else -999.0,
            row.coverage,
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None
    promotion_eligible = False

    all_days = sorted({event.day for event in events})
    holdout_start = int(len(all_days) * 0.80)
    if selected is not None and holdout_start < len(all_days):
        train_end = max(0, holdout_start - PURGE_DAYS)
        train_days = set(all_days[:train_end])
        holdout_days = set(all_days[holdout_start:])
        train_events = tuple(event for event in events if event.day in train_days)
        holdout_events = tuple(event for event in events if event.day in holdout_days)
        model = _fit_model(train_events)
        base = _select_policy_trades(
            model,
            holdout_events,
            threshold_r=selected.threshold_r,
            stressed=False,
        )
        stress = _select_policy_trades(
            model,
            holdout_events,
            threshold_r=selected.threshold_r,
            stressed=True,
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        )
        holdout = {
            "threshold_r": selected.threshold_r,
            "days": len(holdout_days),
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _coverage(holdout_events, base),
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "H1",
        "h1_bars": len(rows),
        "candidate_events": len(events),
        "candidate_days": len({event.day for event in events}),
        "checkpoints_utc": list(CHECKPOINT_HOURS),
        "geometry": {
            "stop_atr": STOP_ATR,
            "target_r": TARGET_R,
            "max_hold_bars": MAX_HOLD_BARS,
            "policy_margin_r": POLICY_MARGIN_R,
        },
        "model": {
            "type": "HistGradientBoostingRegressor",
            "learning_rate": 0.05,
            "max_iter": 160,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 50,
            "l2_regularization": 2.0,
            "random_state": MODEL_RANDOM_STATE,
        },
        "thresholds": [
            {
                "threshold_r": row.threshold_r,
                "base": row.base_metrics.payload(),
                "stressed": row.stressed_metrics.payload(),
                "walk_forward_pass_fraction": row.fold_pass_fraction,
                "folds": list(row.fold_rows),
                "coverage": row.coverage,
                "development_passed": row.development_passed,
            }
            for row in evaluations
        ],
        "selected_threshold_r": None if selected is None else selected.threshold_r,
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "anti_leakage": {
            "final_holdout_fraction": 0.20,
            "purge_days": PURGE_DAYS,
            "decision_policy": "FIRST_CHECKPOINT_PER_DAY_ABOVE_THRESHOLD",
            "holdout_used_for_selection": False,
        },
    }

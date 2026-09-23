from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite, log
from typing import Any, Callable, Sequence

import numpy as np

from .demo_xau_afic_path_shadow_observer import STOP_BUFFER_ATR, _target
from .models import Bar, ensure_utc
from .research_xau_zone_path_v174 import (
    SPLIT_PURGE_HOURS,
    ZoneScenario,
    build_zone_scenarios,
    wilson_lower_bound,
)

RESEARCH_VERSION = "XAU_AFIC_EXECUTION_FUNNEL_V176"
ARTIFACT_CONTRACT = "XAU_AFIC_EXECUTION_FUNNEL_V176_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

CONFIRM_WINDOW_M15 = 8
TARGET_HORIZON_M15 = 32
MIN_TRAIN_ROWS = 40
MIN_CALIBRATION_ROWS = 20
MIN_TEST_ROWS = 20
MIN_DIRECTION_SELECTED = 15
CLAIM_MIN_PER_DIRECTION = 100
CLAIM_TARGET = 0.80
THRESHOLD_GRID = tuple(round(x, 2) for x in np.arange(0.50, 0.91, 0.05))
LOGISTIC_ITERATIONS = 900
LOGISTIC_LEARNING_RATE = 0.04
LOGISTIC_L2 = 0.10

MAP_FEATURE_NAMES = (
    "direction_sign",
    "zone_distance_atr",
    "h4_directional_close_location",
    "zone_age_hours",
    "origin_displacement_range_atr",
    "origin_displacement_body_fraction",
    "zone_width_atr",
    "round_distance_atr",
    "prior_touch_count",
    "approach_efficiency",
    "approach_range_atr",
)

TOUCH_FEATURE_NAMES = MAP_FEATURE_NAMES + (
    "bars_to_touch_norm",
    "touch_depth_atr",
    "touch_favorable_close",
    "touch_rejection_fraction",
    "touch_range_atr",
    "touch_directional_body",
)

CONFIRM_FEATURE_NAMES = TOUCH_FEATURE_NAMES + (
    "confirm_delay_norm",
    "confirm_body_fraction",
    "confirm_range_atr",
    "confirm_close_extension_atr",
    "entry_risk_atr",
    "target_rr",
)


@dataclass(frozen=True, slots=True)
class ExecutionPathOutcome:
    confirmation_status: str
    confirmed: bool
    confirm_at: datetime | None
    confirm_delay_bars: int | None
    target_status: str
    target_hit: bool
    stop_hit: bool
    outcome_at: datetime | None
    entry_at: datetime | None
    entry: float | None
    stop: float | None
    terminal_target: float | None
    target_rr: float | None
    entry_risk_atr: float | None


@dataclass(frozen=True, slots=True)
class FunnelEpisode:
    base: ZoneScenario
    map_features: tuple[float, ...]
    touch_features: tuple[float, ...] | None
    confirm_features: tuple[float, ...] | None
    touch_depth_atr: float | None
    touch_favorable_close: float | None
    touch_rejection_fraction: float | None
    touch_range_atr: float | None
    touch_directional_body: float | None
    execution: ExecutionPathOutcome


@dataclass(frozen=True, slots=True)
class LogisticModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    positive_rate: float
    rows: int


def _touch(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(row: Bar, *, low: float, high: float, direction: str) -> bool:
    if direction == "SHORT":
        return float(row.close) > high
    return float(row.close) < low


def _engulf_reject(
    rows: Sequence[Bar],
    index: int,
    *,
    low: float,
    high: float,
    direction: str,
) -> bool:
    if index <= 0 or not _touch(rows[index], low=low, high=high):
        return False
    prev = rows[index - 1]
    row = rows[index]
    po, pc = float(prev.open), float(prev.close)
    o, c = float(row.open), float(row.close)
    if direction == "SHORT":
        return bool(pc > po and c < o and o >= pc and c <= po and c <= low)
    return bool(pc < po and c > o and o <= pc and c >= po and c >= high)


def _atr_from_scenario(scenario: ZoneScenario) -> float | None:
    width = float(scenario.zone_high) - float(scenario.zone_low)
    width_atr = float(scenario.zone_width_atr)
    if not isfinite(width) or not isfinite(width_atr) or width <= 0 or width_atr <= 0:
        return None
    atr = width / width_atr
    return atr if isfinite(atr) and atr > 0 else None


def _bar_index(
    rows: Sequence[Bar],
    timestamp: datetime | None,
    *,
    index_by_time: dict[datetime, int] | None = None,
) -> int | None:
    if timestamp is None:
        return None
    target = ensure_utc(timestamp)
    if index_by_time is not None:
        return index_by_time.get(target)
    for index, row in enumerate(rows):
        if ensure_utc(row.timestamp) == target:
            return index
    return None


def _touch_features(
    scenario: ZoneScenario,
    rows: Sequence[Bar],
    *,
    touch_index: int,
    atr: float,
) -> tuple[float, float, float, float, float]:
    row = rows[touch_index]
    low = float(scenario.zone_low)
    high = float(scenario.zone_high)
    width = max(high - low, 1e-12)
    rng = max(float(row.high) - float(row.low), 1e-12)
    o, c = float(row.open), float(row.close)

    if scenario.direction == "LONG":
        depth = max(0.0, high - float(row.low)) / atr
        favorable_close = (c - low) / width
        wick = max(0.0, min(o, c) - float(row.low)) / rng
        directional_body = max(0.0, c - o) / rng
    else:
        depth = max(0.0, float(row.high) - low) / atr
        favorable_close = (high - c) / width
        wick = max(0.0, float(row.high) - max(o, c)) / rng
        directional_body = max(0.0, o - c) / rng

    return (
        float(depth),
        float(np.clip(favorable_close, -2.0, 3.0)),
        float(np.clip(wick, 0.0, 1.0)),
        float(rng / atr),
        float(np.clip(directional_body, 0.0, 1.0)),
    )


def _map_features(scenario: ZoneScenario) -> tuple[float, ...]:
    return (
        1.0 if scenario.direction == "LONG" else -1.0,
        float(scenario.zone_distance_atr),
        float(scenario.h4_directional_close_location),
        float(scenario.zone_age_hours),
        float(scenario.origin_displacement_range_atr),
        float(scenario.origin_displacement_body_fraction),
        float(scenario.zone_width_atr),
        float(scenario.round_distance_atr),
        float(scenario.prior_touch_count),
        float(scenario.approach_efficiency),
        float(scenario.approach_range_atr),
    )


def evaluate_execution_funnel_path(
    bars: Sequence[Bar],
    *,
    touch_at: datetime | None,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
    confirm_window_m15: int = CONFIRM_WINDOW_M15,
    target_horizon_m15: int = TARGET_HORIZON_M15,
    _rows_are_sorted: bool = False,
    _index_by_time: dict[datetime, int] | None = None,
) -> ExecutionPathOutcome:
    rows = (
        tuple(bars)
        if _rows_are_sorted
        else tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    )
    index_by_time = (
        _index_by_time
        if _index_by_time is not None
        else {ensure_utc(row.timestamp): index for index, row in enumerate(rows)}
    )
    normalized = str(direction).upper().strip()
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("zone bounds must be finite and ordered")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_points must be positive and finite")
    if touch_at is None:
        return ExecutionPathOutcome(
            confirmation_status="NOT_TOUCHED",
            confirmed=False,
            confirm_at=None,
            confirm_delay_bars=None,
            target_status="NOT_APPLICABLE",
            target_hit=False,
            stop_hit=False,
            outcome_at=None,
            entry_at=None,
            entry=None,
            stop=None,
            terminal_target=None,
            target_rr=None,
            entry_risk_atr=None,
        )

    touch_index = _bar_index(rows, touch_at, index_by_time=index_by_time)
    if touch_index is None:
        return ExecutionPathOutcome(
            confirmation_status="TOUCH_BAR_NOT_FOUND",
            confirmed=False,
            confirm_at=None,
            confirm_delay_bars=None,
            target_status="NOT_APPLICABLE",
            target_hit=False,
            stop_hit=False,
            outcome_at=None,
            entry_at=None,
            entry=None,
            stop=None,
            terminal_target=None,
            target_rr=None,
            entry_risk_atr=None,
        )

    confirm_index: int | None = None
    confirm_end = min(len(rows) - 1, touch_index + int(confirm_window_m15))
    for index in range(touch_index, confirm_end + 1):
        if _invalidated(rows[index], low=low, high=high, direction=normalized):
            return ExecutionPathOutcome(
                confirmation_status="INVALIDATED_BEFORE_CONFIRM",
                confirmed=False,
                confirm_at=None,
                confirm_delay_bars=None,
                target_status="NOT_APPLICABLE",
                target_hit=False,
                stop_hit=False,
                outcome_at=ensure_utc(rows[index].timestamp),
                entry_at=None,
                entry=None,
                stop=None,
                terminal_target=None,
                target_rr=None,
                entry_risk_atr=None,
            )
        if _engulf_reject(
            rows,
            index,
            low=low,
            high=high,
            direction=normalized,
        ):
            confirm_index = index
            break

    if confirm_index is None:
        enough = len(rows) > touch_index + int(confirm_window_m15)
        return ExecutionPathOutcome(
            confirmation_status="CONFIRM_TIMEOUT" if enough else "PENDING_CONFIRM",
            confirmed=False,
            confirm_at=None,
            confirm_delay_bars=None,
            target_status="NOT_APPLICABLE",
            target_hit=False,
            stop_hit=False,
            outcome_at=(
                ensure_utc(rows[touch_index + int(confirm_window_m15)].timestamp)
                if enough
                else None
            ),
            entry_at=None,
            entry=None,
            stop=None,
            terminal_target=None,
            target_rr=None,
            entry_risk_atr=None,
        )

    entry_index = confirm_index + 1
    confirm_at = ensure_utc(rows[confirm_index].timestamp)
    if entry_index >= len(rows):
        return ExecutionPathOutcome(
            confirmation_status="CONFIRMED",
            confirmed=True,
            confirm_at=confirm_at,
            confirm_delay_bars=confirm_index - touch_index,
            target_status="PENDING_ENTRY",
            target_hit=False,
            stop_hit=False,
            outcome_at=None,
            entry_at=None,
            entry=None,
            stop=None,
            terminal_target=None,
            target_rr=None,
            entry_risk_atr=None,
        )

    entry = float(rows[entry_index].open)
    stop = low - STOP_BUFFER_ATR * atr if normalized == "LONG" else high + STOP_BUFFER_ATR * atr
    target_geometry = _target(entry, stop, normalized)
    if target_geometry is None:
        return ExecutionPathOutcome(
            confirmation_status="CONFIRMED",
            confirmed=True,
            confirm_at=confirm_at,
            confirm_delay_bars=confirm_index - touch_index,
            target_status="TARGET_GEOMETRY_INVALID",
            target_hit=False,
            stop_hit=False,
            outcome_at=None,
            entry_at=ensure_utc(rows[entry_index].timestamp),
            entry=entry,
            stop=stop,
            terminal_target=None,
            target_rr=None,
            entry_risk_atr=abs(entry - stop) / atr,
        )

    _, terminal_target, _ = target_geometry
    risk = abs(entry - stop)
    target_rr = abs(float(terminal_target) - entry) / risk if risk > 0 else None
    entry_at = ensure_utc(rows[entry_index].timestamp)
    end_index = min(len(rows), entry_index + int(target_horizon_m15))
    for index in range(entry_index, end_index):
        row = rows[index]
        if normalized == "LONG":
            stop_hit = float(row.low) <= stop
            target_hit = float(row.high) >= float(terminal_target)
        else:
            stop_hit = float(row.high) >= stop
            target_hit = float(row.low) <= float(terminal_target)
        if stop_hit:
            return ExecutionPathOutcome(
                confirmation_status="CONFIRMED",
                confirmed=True,
                confirm_at=confirm_at,
                confirm_delay_bars=confirm_index - touch_index,
                target_status="STOP_HIT",
                target_hit=False,
                stop_hit=True,
                outcome_at=ensure_utc(row.timestamp),
                entry_at=entry_at,
                entry=entry,
                stop=stop,
                terminal_target=float(terminal_target),
                target_rr=target_rr,
                entry_risk_atr=risk / atr,
            )
        if target_hit:
            return ExecutionPathOutcome(
                confirmation_status="CONFIRMED",
                confirmed=True,
                confirm_at=confirm_at,
                confirm_delay_bars=confirm_index - touch_index,
                target_status="TARGET_HIT",
                target_hit=True,
                stop_hit=False,
                outcome_at=ensure_utc(row.timestamp),
                entry_at=entry_at,
                entry=entry,
                stop=stop,
                terminal_target=float(terminal_target),
                target_rr=target_rr,
                entry_risk_atr=risk / atr,
            )

    enough_target_history = len(rows) >= entry_index + int(target_horizon_m15)
    return ExecutionPathOutcome(
        confirmation_status="CONFIRMED",
        confirmed=True,
        confirm_at=confirm_at,
        confirm_delay_bars=confirm_index - touch_index,
        target_status="TARGET_TIMEOUT" if enough_target_history else "PENDING_TARGET",
        target_hit=False,
        stop_hit=False,
        outcome_at=(
            ensure_utc(rows[entry_index + int(target_horizon_m15) - 1].timestamp)
            if enough_target_history
            else None
        ),
        entry_at=entry_at,
        entry=entry,
        stop=stop,
        terminal_target=float(terminal_target),
        target_rr=target_rr,
        entry_risk_atr=risk / atr,
    )


def build_funnel_episodes(bars: Sequence[Bar]) -> tuple[FunnelEpisode, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    index_by_time = {
        ensure_utc(row.timestamp): index for index, row in enumerate(rows)
    }
    scenarios = build_zone_scenarios(rows)
    out: list[FunnelEpisode] = []
    for scenario in scenarios:
        atr = _atr_from_scenario(scenario)
        if atr is None:
            continue
        base_features = _map_features(scenario)
        touch_features: tuple[float, ...] | None = None
        confirm_features: tuple[float, ...] | None = None
        touch_depth = touch_close = touch_wick = touch_range = touch_body = None
        touch_index = _bar_index(
            rows,
            scenario.outcome.touch_at,
            index_by_time=index_by_time,
        )
        if scenario.outcome.touched and touch_index is not None:
            touch_depth, touch_close, touch_wick, touch_range, touch_body = _touch_features(
                scenario,
                rows,
                touch_index=touch_index,
                atr=atr,
            )
            bars_to_touch = float(scenario.outcome.bars_to_touch or 0) / 64.0
            touch_features = base_features + (
                bars_to_touch,
                touch_depth,
                touch_close,
                touch_wick,
                touch_range,
                touch_body,
            )

        execution = evaluate_execution_funnel_path(
            rows,
            touch_at=scenario.outcome.touch_at if scenario.outcome.touched else None,
            direction=scenario.direction,
            zone_low=scenario.zone_low,
            zone_high=scenario.zone_high,
            atr_points=atr,
            _rows_are_sorted=True,
            _index_by_time=index_by_time,
        )

        if touch_features is not None and execution.confirmed and execution.confirm_at is not None:
            confirm_index = _bar_index(
                rows,
                execution.confirm_at,
                index_by_time=index_by_time,
            )
            if confirm_index is not None:
                row = rows[confirm_index]
                rng = max(float(row.high) - float(row.low), 1e-12)
                body = abs(float(row.close) - float(row.open))
                if scenario.direction == "LONG":
                    extension = max(0.0, float(row.close) - float(scenario.zone_high)) / atr
                else:
                    extension = max(0.0, float(scenario.zone_low) - float(row.close)) / atr
                confirm_features = touch_features + (
                    float(execution.confirm_delay_bars or 0) / float(CONFIRM_WINDOW_M15),
                    float(body / rng),
                    float(rng / atr),
                    float(extension),
                    float(execution.entry_risk_atr or 0.0),
                    float(execution.target_rr or 0.0),
                )

        out.append(
            FunnelEpisode(
                base=scenario,
                map_features=base_features,
                touch_features=touch_features,
                confirm_features=confirm_features,
                touch_depth_atr=touch_depth,
                touch_favorable_close=touch_close,
                touch_rejection_fraction=touch_wick,
                touch_range_atr=touch_range,
                touch_directional_body=touch_body,
                execution=execution,
            )
        )
    return tuple(out)


def _split_by_map(
    episodes: Sequence[FunnelEpisode],
) -> tuple[tuple[FunnelEpisode, ...], tuple[FunnelEpisode, ...], tuple[FunnelEpisode, ...]]:
    maps = sorted({episode.base.map_at for episode in episodes})
    if len(maps) < 10:
        return (), (), ()
    train_index = int(len(maps) * 0.60)
    calibration_index = int(len(maps) * 0.80)
    if train_index <= 0 or calibration_index <= train_index or calibration_index >= len(maps):
        return (), (), ()
    calibration_start = maps[train_index]
    test_start = maps[calibration_index]
    purge = timedelta(hours=max(24, SPLIT_PURGE_HOURS))
    train = tuple(
        episode
        for episode in episodes
        if episode.base.map_at < calibration_start - purge
    )
    calibration = tuple(
        episode
        for episode in episodes
        if calibration_start <= episode.base.map_at < test_start - purge
    )
    test = tuple(episode for episode in episodes if episode.base.map_at >= test_start)
    return train, calibration, test


def _fit_logistic(
    rows: Sequence[FunnelEpisode],
    *,
    feature_names: tuple[str, ...],
    feature_getter: Callable[[FunnelEpisode], tuple[float, ...] | None],
    label_getter: Callable[[FunnelEpisode], bool],
) -> LogisticModel:
    selected = [(feature_getter(row), label_getter(row)) for row in rows]
    selected = [(features, label) for features, label in selected if features is not None]
    if len(selected) < MIN_TRAIN_ROWS:
        raise ValueError(f"insufficient training rows:{len(selected)}")
    matrix = np.asarray([features for features, _ in selected], dtype=float)
    labels = np.asarray([float(label) for _, label in selected], dtype=float)
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    normalized = np.clip((matrix - means) / scales, -8.0, 8.0)
    coefficients = np.zeros(normalized.shape[1], dtype=float)
    positive_rate = float(np.mean(labels))
    intercept = float(log((positive_rate + 1e-6) / (1.0 - positive_rate + 1e-6)))
    for _ in range(LOGISTIC_ITERATIONS):
        logits = np.clip(normalized @ coefficients + intercept, -30.0, 30.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = probabilities - labels
        gradient = (
            normalized.T @ errors / len(labels)
            + LOGISTIC_L2 * coefficients / len(labels)
        )
        intercept_gradient = float(np.mean(errors))
        coefficients -= LOGISTIC_LEARNING_RATE * gradient
        intercept -= LOGISTIC_LEARNING_RATE * intercept_gradient
    return LogisticModel(
        feature_names=feature_names,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        positive_rate=positive_rate,
        rows=len(selected),
    )


def _predict(model: LogisticModel, features: tuple[float, ...]) -> float:
    vector = np.asarray(features, dtype=float)
    means = np.asarray(model.means, dtype=float)
    scales = np.asarray(model.scales, dtype=float)
    coefficients = np.asarray(model.coefficients, dtype=float)
    normalized = np.clip((vector - means) / scales, -8.0, 8.0)
    logit_value = float(np.clip(normalized @ coefficients + model.intercept, -30.0, 30.0))
    return float(1.0 / (1.0 + np.exp(-logit_value)))


def _stage_population(
    rows: Sequence[FunnelEpisode], stage: str
) -> tuple[FunnelEpisode, ...]:
    if stage == "touch":
        return tuple(
            row
            for row in rows
            if row.base.outcome.status not in {"PENDING_TOUCH", "PENDING_REACTION"}
        )
    if stage == "reaction":
        return tuple(
            row
            for row in rows
            if row.touch_features is not None
            and row.base.outcome.status not in {"PENDING_TOUCH", "PENDING_REACTION"}
        )
    if stage == "confirmation":
        return tuple(
            row
            for row in rows
            if row.touch_features is not None
            and row.execution.confirmation_status not in {"PENDING_CONFIRM", "TOUCH_BAR_NOT_FOUND"}
        )
    if stage == "target":
        return tuple(
            row
            for row in rows
            if row.confirm_features is not None
            and row.execution.target_status
            in {"TARGET_HIT", "STOP_HIT", "TARGET_TIMEOUT"}
        )
    raise ValueError(f"unknown stage:{stage}")


def _stage_spec(stage: str):
    if stage == "touch":
        return MAP_FEATURE_NAMES, lambda row: row.map_features, lambda row: row.base.outcome.touched
    if stage == "reaction":
        return (
            TOUCH_FEATURE_NAMES,
            lambda row: row.touch_features,
            lambda row: row.base.outcome.reversed_after_touch,
        )
    if stage == "confirmation":
        return (
            TOUCH_FEATURE_NAMES,
            lambda row: row.touch_features,
            lambda row: row.execution.confirmed,
        )
    if stage == "target":
        return (
            CONFIRM_FEATURE_NAMES,
            lambda row: row.confirm_features,
            lambda row: row.execution.target_hit,
        )
    raise ValueError(f"unknown stage:{stage}")


def _model_payload(model: LogisticModel) -> dict[str, Any]:
    ranked = sorted(
        zip(model.feature_names, model.coefficients),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    return {
        "rows": model.rows,
        "positive_rate": model.positive_rate,
        "intercept": model.intercept,
        "top_absolute_coefficients": [
            {"feature": name, "coefficient": coefficient}
            for name, coefficient in ranked[:10]
        ],
    }


def _score_stage(
    rows: Sequence[FunnelEpisode],
    *,
    stage: str,
    model: LogisticModel,
) -> tuple[tuple[FunnelEpisode, float, bool], ...]:
    _, feature_getter, label_getter = _stage_spec(stage)
    scored = []
    for row in _stage_population(rows, stage):
        features = feature_getter(row)
        if features is None:
            continue
        scored.append((row, _predict(model, features), bool(label_getter(row))))
    return tuple(scored)


def _brier(scored: Sequence[tuple[FunnelEpisode, float, bool]]) -> float | None:
    if not scored:
        return None
    return float(np.mean([(probability - float(label)) ** 2 for _, probability, label in scored]))


def _calibration_bins(
    scored: Sequence[tuple[FunnelEpisode, float, bool]],
) -> list[dict[str, Any]]:
    if not scored:
        return []
    bins = []
    for lower in np.arange(0.0, 1.0, 0.1):
        upper = min(1.0, lower + 0.1)
        selected = [
            item
            for item in scored
            if (lower <= item[1] < upper) or (upper == 1.0 and item[1] == 1.0)
        ]
        if not selected:
            continue
        bins.append(
            {
                "bin": f"{lower:.1f}-{upper:.1f}",
                "rows": len(selected),
                "predicted_mean": float(np.mean([item[1] for item in selected])),
                "observed_rate": float(np.mean([float(item[2]) for item in selected])),
            }
        )
    return bins


def _threshold_report(
    scored: Sequence[tuple[FunnelEpisode, float, bool]],
    *,
    threshold: float,
    direction: str,
) -> dict[str, Any]:
    universe = [item for item in scored if item[0].base.direction == direction]
    selected = [item for item in universe if item[1] >= threshold]
    hits = sum(label for _, _, label in selected)
    return {
        "direction": direction,
        "threshold": threshold,
        "universe": len(universe),
        "selected": len(selected),
        "coverage": None if not universe else len(selected) / len(universe),
        "hits": int(hits),
        "precision": None if not selected else hits / len(selected),
        "wilson_lower_95": wilson_lower_bound(int(hits), len(selected)),
        "mean_probability": None if not selected else float(np.mean([item[1] for item in selected])),
    }


def _choose_threshold(
    scored: Sequence[tuple[FunnelEpisode, float, bool]],
    *,
    direction: str,
) -> tuple[float, dict[str, Any]]:
    candidates = []
    for threshold in THRESHOLD_GRID:
        report = _threshold_report(scored, threshold=threshold, direction=direction)
        if report["selected"] < MIN_DIRECTION_SELECTED:
            continue
        candidates.append(report)
    if not candidates:
        fallback = _threshold_report(scored, threshold=0.50, direction=direction)
        return 0.50, fallback | {"selection_reason": "FALLBACK_MIN_SAMPLE_NOT_MET"}
    best = max(
        candidates,
        key=lambda row: (
            float(row["wilson_lower_95"] or 0.0),
            float(row["precision"] or 0.0),
            float(row["coverage"] or 0.0),
        ),
    )
    return float(best["threshold"]), best | {"selection_reason": "MAX_WILSON_ON_CALIBRATION"}


def _stage_evaluation(
    *,
    stage: str,
    train: Sequence[FunnelEpisode],
    calibration: Sequence[FunnelEpisode],
    test: Sequence[FunnelEpisode],
) -> tuple[dict[str, Any], LogisticModel, dict[str, float]]:
    feature_names, feature_getter, label_getter = _stage_spec(stage)
    train_population = _stage_population(train, stage)
    calibration_population = _stage_population(calibration, stage)
    test_population = _stage_population(test, stage)
    if (
        len(train_population) < MIN_TRAIN_ROWS
        or len(calibration_population) < MIN_CALIBRATION_ROWS
        or len(test_population) < MIN_TEST_ROWS
    ):
        raise ValueError(
            f"{stage} insufficient split rows:"
            f"{len(train_population)}/{len(calibration_population)}/{len(test_population)}"
        )

    model = _fit_logistic(
        train_population,
        feature_names=feature_names,
        feature_getter=feature_getter,
        label_getter=label_getter,
    )
    calibration_scored = _score_stage(calibration_population, stage=stage, model=model)
    test_scored = _score_stage(test_population, stage=stage, model=model)

    thresholds: dict[str, float] = {}
    calibration_thresholds: dict[str, Any] = {}
    untouched: dict[str, Any] = {}
    claim_direction = []
    for direction in ("LONG", "SHORT"):
        threshold, calibration_report = _choose_threshold(
            calibration_scored,
            direction=direction,
        )
        thresholds[direction] = threshold
        calibration_thresholds[direction] = calibration_report
        test_report = _threshold_report(
            test_scored,
            threshold=threshold,
            direction=direction,
        )
        untouched[direction] = test_report
        claim_direction.append(
            test_report["selected"] >= CLAIM_MIN_PER_DIRECTION
            and (test_report["precision"] or 0.0) >= CLAIM_TARGET
            and (test_report["wilson_lower_95"] or 0.0) >= CLAIM_TARGET
        )

    return (
        {
            "stage": stage,
            "population": {
                "train": len(train_population),
                "calibration": len(calibration_population),
                "test": len(test_population),
            },
            "model": _model_payload(model),
            "calibration_thresholds": calibration_thresholds,
            "thresholds": thresholds,
            "untouched_test": untouched,
            "untouched_test_brier": _brier(test_scored),
            "untouched_test_calibration_bins": _calibration_bins(test_scored),
            "claim_gate": {
                "target_precision": CLAIM_TARGET,
                "minimum_selected_per_direction": CLAIM_MIN_PER_DIRECTION,
                "requires_wilson_lower_95_at_target": True,
                "passed": all(claim_direction),
            },
        },
        model,
        thresholds,
    )


def _stacked_funnel(
    test: Sequence[FunnelEpisode],
    *,
    models: dict[str, LogisticModel],
    thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    by_direction: dict[str, Any] = {}
    for direction in ("LONG", "SHORT"):
        maps = [row for row in _stage_population(test, "touch") if row.base.direction == direction]
        touch_selected = [
            row for row in maps
            if _predict(models["touch"], row.map_features) >= thresholds["touch"][direction]
        ]
        touched = [row for row in touch_selected if row.base.outcome.touched and row.touch_features is not None]
        reaction_selected = [
            row for row in touched
            if _predict(models["reaction"], row.touch_features or ()) >= thresholds["reaction"][direction]
        ]
        reacted = [row for row in reaction_selected if row.base.outcome.reversed_after_touch]
        confirm_candidates = [
            row for row in reaction_selected
            if row.execution.confirmation_status not in {"PENDING_CONFIRM", "TOUCH_BAR_NOT_FOUND"}
        ]
        confirmation_selected = [
            row for row in confirm_candidates
            if _predict(models["confirmation"], row.touch_features or ()) >= thresholds["confirmation"][direction]
        ]
        confirmed = [
            row for row in confirmation_selected
            if row.execution.confirmed and row.confirm_features is not None
        ]
        target_population = [
            row for row in confirmed
            if row.execution.target_status in {"TARGET_HIT", "STOP_HIT", "TARGET_TIMEOUT"}
        ]
        target_selected = [
            row for row in target_population
            if _predict(models["target"], row.confirm_features or ()) >= thresholds["target"][direction]
        ]
        target_hits = sum(row.execution.target_hit for row in target_selected)
        by_direction[direction] = {
            "maps": len(maps),
            "touch_model_selected": len(touch_selected),
            "actual_touches": len(touched),
            "reaction_model_selected": len(reaction_selected),
            "actual_reactions": len(reacted),
            "confirmation_model_selected": len(confirmation_selected),
            "actual_confirmations": len(confirmed),
            "target_model_selected": len(target_selected),
            "actual_target_hits": int(target_hits),
            "map_to_target_precision": None
            if not touch_selected
            else target_hits / len(touch_selected),
            "confirmed_to_target_precision": None
            if not target_selected
            else target_hits / len(target_selected),
            "target_wilson_lower_95": wilson_lower_bound(int(target_hits), len(target_selected)),
        }
    return by_direction


def evaluate_execution_funnel_research(bars: Sequence[Bar]) -> dict[str, Any]:
    episodes = build_funnel_episodes(bars)
    train, calibration, test = _split_by_map(episodes)
    base = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "label_contract": {
            "touch": "V174 causal zone touch within 64 M15 bars; invalidation wins ambiguity",
            "reaction": "V174 0.75 ATR reversal within 8 M15 bars after touch",
            "confirmation": "exact AFIC M15 engulf/rejection within 8 M15 bars after touch",
            "target": "current AFIC terminal target geometry after next-bar-open entry; stop wins same-bar ambiguity",
            "target_horizon_m15": TARGET_HORIZON_M15,
            "split": "60/20/20 chronological maps with >=24h purge",
        },
        "episodes": len(episodes),
        "unique_maps": len({episode.base.map_at for episode in episodes}),
        "split": {
            "train": len(train),
            "calibration": len(calibration),
            "test": len(test),
            "purge_hours": max(24, SPLIT_PURGE_HOURS),
        },
    }
    if min(len(train), len(calibration), len(test)) <= 0:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT",
            "reason": "EMPTY_TRAIN_CALIBRATION_OR_TEST",
        }

    stage_results: dict[str, Any] = {}
    models: dict[str, LogisticModel] = {}
    thresholds: dict[str, dict[str, float]] = {}
    try:
        for stage in ("touch", "reaction", "confirmation", "target"):
            result, model, stage_thresholds = _stage_evaluation(
                stage=stage,
                train=train,
                calibration=calibration,
                test=test,
            )
            stage_results[stage] = result
            models[stage] = model
            thresholds[stage] = stage_thresholds
    except ValueError as exc:
        return base | {
            "stages": stage_results,
            "decision": "DATA_INSUFFICIENT_FOR_STAGE_MODEL",
            "reason": str(exc),
        }

    claim_passed = all(result["claim_gate"]["passed"] for result in stage_results.values())
    return base | {
        "models": {
            "touch": "P(zone reached | map)",
            "reaction": "P(reversal_0.75ATR | zone reached)",
            "confirmation": "P(exact M15 AFIC confirmation | zone reached)",
            "target": "P(terminal target | exact M15 AFIC confirmation)",
        },
        "stages": stage_results,
        "stacked_untouched_test": _stacked_funnel(
            test,
            models=models,
            thresholds=thresholds,
        ),
        "claim_gate": {
            "target_precision": CLAIM_TARGET,
            "all_four_stages_must_pass": True,
            "passed": claim_passed,
        },
        "decision": (
            "RESEARCH_STAGE_GATES_MET"
            if claim_passed
            else "RESEARCH_ONLY_STAGE_GATES_NOT_MET"
        ),
        "notes": [
            "V176 complements V175 instead of replacing it: V175 ranks competing zones; V176 audits the canonical AFIC execution funnel.",
            "Every feature used by a stage is available at or before that stage's decision time.",
            "Thresholds are selected only on calibration data and evaluated once on untouched chronological test data.",
            "No V176 probability or threshold has broker execution authority.",
        ],
    }

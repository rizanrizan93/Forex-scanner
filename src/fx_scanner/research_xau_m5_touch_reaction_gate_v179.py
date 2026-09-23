from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .demo_xau_afic_path_shadow_observer import (
    _atr,
    _origin_zones,
    _resample_completed,
    _stable_zone_id,
)
from .models import Bar, ensure_utc
from .research_xau_h1_origin_hold_break_m5_v178 import (
    FEATURE_NAMES as PRE_TOUCH_FEATURE_NAMES,
    MAX_ZONE_AGE_HOURS,
    PRE_TOUCH_M5_BARS,
    PURGE_HOURS,
    _feature_vector as _pre_touch_feature_vector,
    _frame_times,
    _frame_trend_context,
    _invalidated,
    _touch,
    _validate_bars,
)
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_M5_TOUCH_REACTION_GATE_V179"
ARTIFACT_CONTRACT = "XAU_M5_TOUCH_REACTION_GATE_V179_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "XAUUSD"
REACTION_ATR = 0.50
FUTURE_HORIZON_M5 = 48
TRAIN_FRACTION = 0.50
CALIBRATION_FRACTION = 0.20
HOLDOUT_FRACTION = 0.30

CLAIM_PRECISION = 0.80
MIN_CLAIM_PER_DIRECTION = 100
MIN_TRAIN_PER_DIRECTION = 80
MIN_CALIBRATION_SELECTED_PER_DIRECTION = 75
MIN_CALIBRATION_COVERAGE = 0.05
THRESHOLD_GRID = tuple(round(value, 2) for value in np.arange(0.35, 0.91, 0.05))

LOGISTIC_ITERATIONS = 1400
LOGISTIC_LEARNING_RATE = 0.03
LOGISTIC_L2 = 0.18

TOUCH_FEATURE_NAMES = (
    "touch_penetration_atr",
    "touch_close_reclaim_atr",
    "touch_close_zone_location",
    "touch_rejection_wick_fraction",
    "touch_directional_body_fraction",
    "touch_range_atr",
    "touch_zone_overlap_fraction",
    "touch_tick_to_prior3",
    "touch_tick_to_prior12",
    "touch_tick_to_prior36",
    "touch_range_to_prior12",
    "touch_body_to_prior12",
    "touch_gap_directional_atr",
    "touch_reclaim_flag",
    "touch_favorable_close_flag",
    "touch_deep_penetration_x_reclaim",
    "touch_activity_x_rejection",
)

FEATURE_NAMES = PRE_TOUCH_FEATURE_NAMES + TOUCH_FEATURE_NAMES


@dataclass(frozen=True, slots=True)
class FutureOutcome:
    status: str
    label_hold: bool
    outcome_at: datetime | None
    bars_to_outcome: int | None
    max_favorable_excursion_atr: float


@dataclass(frozen=True, slots=True)
class Episode:
    zone_id: str
    direction: str
    available_at: datetime
    touch_at: datetime
    decision_at: datetime
    zone_low: float
    zone_high: float
    features: tuple[float, ...]
    touch_reclaim_atr: float
    touch_rejection_wick_fraction: float
    touch_penetration_atr: float
    touch_favorable_close: bool
    outcome: FutureOutcome


@dataclass(frozen=True, slots=True)
class LogisticModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    positive_rate: float
    rows: int


@dataclass(frozen=True, slots=True)
class ScoredEpisode:
    episode: Episode
    probability_hold: float


def _safe_ratio(
    numerator: float,
    denominator: float,
    *,
    default: float = 0.0,
) -> float:
    if (
        not isfinite(numerator)
        or not isfinite(denominator)
        or abs(denominator) < 1e-12
    ):
        return default
    return float(numerator / denominator)


def _future_favorable_excursion(
    row: Bar,
    *,
    low: float,
    high: float,
    direction: str,
) -> float:
    if direction == "LONG":
        return max(0.0, float(row.high) - high)
    return max(0.0, low - float(row.low))


def evaluate_future_outcome(
    bars: Sequence[Bar],
    *,
    touch_index: int,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
    horizon_m5: int = FUTURE_HORIZON_M5,
    reaction_atr: float = REACTION_ATR,
) -> FutureOutcome:
    rows = tuple(bars)
    direction = str(direction).upper()
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("V179_DIRECTION_INVALID")
    if not (0 <= touch_index < len(rows)):
        raise ValueError("V179_TOUCH_INDEX_INVALID")
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("V179_ZONE_INVALID")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("V179_ATR_INVALID")

    future = rows[touch_index + 1 : touch_index + 1 + int(horizon_m5)]
    max_excursion = 0.0
    for offset, row in enumerate(future, start=1):
        max_excursion = max(
            max_excursion,
            _future_favorable_excursion(
                row,
                low=low,
                high=high,
                direction=direction,
            ),
        )
        # Fail closed: a close beyond the zone invalidation boundary wins
        # ambiguity within the same future M5 bar.
        if _invalidated(
            row,
            low=low,
            high=high,
            direction=direction,
        ):
            return FutureOutcome(
                status="BREAK",
                label_hold=False,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )
        if max_excursion + 1e-12 >= float(reaction_atr) * atr:
            return FutureOutcome(
                status="HOLD",
                label_hold=True,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )

    if len(future) < int(horizon_m5):
        return FutureOutcome(
            status="PENDING",
            label_hold=False,
            outcome_at=None,
            bars_to_outcome=None,
            max_favorable_excursion_atr=max_excursion / atr,
        )

    return FutureOutcome(
        status="STALL",
        label_hold=False,
        outcome_at=ensure_utc(future[-1].timestamp),
        bars_to_outcome=int(horizon_m5),
        max_favorable_excursion_atr=max_excursion / atr,
    )


def _touch_features(
    *,
    touch: Bar,
    prior_m5: Sequence[Bar],
    direction: str,
    low: float,
    high: float,
    atr: float,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    if len(prior_m5) < PRE_TOUCH_M5_BARS:
        raise ValueError("V179_PRE_TOUCH_HISTORY_INSUFFICIENT")
    direction = str(direction).upper()
    width = max(high - low, 1e-12)
    open_ = float(touch.open)
    close = float(touch.close)
    touch_high = float(touch.high)
    touch_low = float(touch.low)
    rng = max(touch_high - touch_low, 1e-12)
    body = abs(close - open_)

    if direction == "LONG":
        penetration = max(0.0, high - touch_low) / atr
        reclaim = (close - high) / atr
        close_location = (close - low) / width
        rejection_wick = max(0.0, min(open_, close) - touch_low) / rng
        directional_body = max(0.0, close - open_) / rng
        gap_directional = (close - float(prior_m5[-1].close)) / atr
        favorable_close = close >= open_
    else:
        penetration = max(0.0, touch_high - low) / atr
        reclaim = (low - close) / atr
        close_location = (high - close) / width
        rejection_wick = max(0.0, touch_high - max(open_, close)) / rng
        directional_body = max(0.0, open_ - close) / rng
        gap_directional = (float(prior_m5[-1].close) - close) / atr
        favorable_close = close <= open_

    overlap = max(
        0.0,
        min(touch_high, high) - max(touch_low, low),
    ) / width

    prior3 = prior_m5[-3:]
    prior12 = prior_m5[-12:]
    prior36 = prior_m5[-36:]
    tick = float(touch.tick_count)
    tick3 = float(np.mean([float(row.tick_count) for row in prior3]))
    tick12 = float(np.mean([float(row.tick_count) for row in prior12]))
    tick36 = float(np.mean([float(row.tick_count) for row in prior36]))
    prior_range12 = float(
        np.mean([float(row.high) - float(row.low) for row in prior12])
    )
    prior_body12 = float(
        np.mean(
            [
                abs(float(row.close) - float(row.open))
                for row in prior12
            ]
        )
    )

    reclaim_flag = float(reclaim >= 0.0)
    favorable_flag = float(favorable_close)
    values = (
        float(np.clip(penetration, 0.0, 8.0)),
        float(np.clip(reclaim, -8.0, 8.0)),
        float(np.clip(close_location, -3.0, 4.0)),
        float(np.clip(rejection_wick, 0.0, 1.0)),
        float(np.clip(directional_body, 0.0, 1.0)),
        float(np.clip(rng / atr, 0.0, 8.0)),
        float(np.clip(overlap, 0.0, 1.0)),
        float(np.clip(_safe_ratio(tick, tick3, default=1.0), 0.0, 8.0)),
        float(np.clip(_safe_ratio(tick, tick12, default=1.0), 0.0, 8.0)),
        float(np.clip(_safe_ratio(tick, tick36, default=1.0), 0.0, 8.0)),
        float(
            np.clip(
                _safe_ratio(rng, prior_range12, default=1.0),
                0.0,
                8.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(body, prior_body12, default=1.0),
                0.0,
                8.0,
            )
        ),
        float(np.clip(gap_directional, -8.0, 8.0)),
        reclaim_flag,
        favorable_flag,
        float(np.clip(penetration * reclaim, -16.0, 16.0)),
        float(
            np.clip(
                _safe_ratio(tick, tick12, default=1.0)
                * rejection_wick,
                0.0,
                8.0,
            )
        ),
    )
    if len(values) != len(TOUCH_FEATURE_NAMES):
        raise ValueError("V179_TOUCH_FEATURE_CONTRACT")
    if not all(isfinite(value) for value in values):
        raise ValueError("V179_TOUCH_FEATURE_NONFINITE")
    return values, {
        "reclaim_atr": float(reclaim),
        "rejection_wick_fraction": float(rejection_wick),
        "penetration_atr": float(penetration),
        "favorable_close": bool(favorable_close),
        "touch_favorable_excursion_atr": (
            max(0.0, touch_high - high) / atr
            if direction == "LONG"
            else max(0.0, low - touch_low) / atr
        ),
    }


def build_episodes(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> tuple[Episode, ...]:
    m15 = _validate_bars(m15_bars, timeframe="M15")
    m5 = _validate_bars(m5_bars, timeframe="M5")
    if len(m15) < 5_000 or len(m5) < 20_000:
        return ()

    last_closed_at = min(
        ensure_utc(m15[-1].timestamp) + timedelta(minutes=15),
        ensure_utc(m5[-1].timestamp) + timedelta(minutes=5),
    )

    h4 = _resample_completed(m15, "4h", as_of=last_closed_at)
    h4["ema20"] = h4["close"].ewm(span=20, adjust=False).mean()
    h4["atr14"] = _atr(h4, 14)
    h4["atr5"] = _atr(h4, 5)
    h4["atr20"] = _atr(h4, 20)

    daily = _resample_completed(m15, "1D", as_of=last_closed_at)
    daily["ema20"] = daily["close"].ewm(span=20, adjust=False).mean()
    daily["atr14"] = _atr(daily, 14)
    daily["atr5"] = _atr(daily, 5)
    daily["atr20"] = _atr(daily, 20)

    h4_times = _frame_times(h4)
    daily_times = _frame_times(daily)
    m5_times = tuple(ensure_utc(row.timestamp) for row in m5)
    zones = _origin_zones(m15, as_of=last_closed_at)

    output: list[Episode] = []
    for zone in zones:
        direction = str(zone.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        atr = float(zone.h1_atr)
        if not isfinite(atr) or atr <= 0:
            continue

        available_at = ensure_utc(zone.available_at)
        if available_at < m5_times[0] or available_at > m5_times[-1]:
            continue
        start_index = bisect_left(m5_times, available_at)
        end_index = min(
            len(m5),
            bisect_right(
                m5_times,
                available_at + timedelta(hours=MAX_ZONE_AGE_HOURS),
            ),
        )

        touch_index: int | None = None
        for index in range(start_index, end_index):
            if _touch(
                m5[index],
                low=float(zone.low),
                high=float(zone.high),
            ):
                touch_index = index
                break

        if (
            touch_index is None
            or touch_index < PRE_TOUCH_M5_BARS
            or touch_index + FUTURE_HORIZON_M5 >= len(m5)
        ):
            continue

        touch = m5[touch_index]
        # A completed touch bar that already closes through invalidation is
        # deterministically rejected, not sent into the stochastic classifier.
        if _invalidated(
            touch,
            low=float(zone.low),
            high=float(zone.high),
            direction=direction,
        ):
            continue

        prior = m5[touch_index - PRE_TOUCH_M5_BARS : touch_index]
        if len(prior) < PRE_TOUCH_M5_BARS:
            continue

        decision_at = ensure_utc(touch.timestamp) + timedelta(minutes=5)
        pre_features = _pre_touch_feature_vector(
            zone=zone,
            prior_m5=prior,
            decision_at=ensure_utc(touch.timestamp),
            h4=h4,
            h4_times=h4_times,
            daily=daily,
            daily_times=daily_times,
        )
        touch_features, touch_meta = _touch_features(
            touch=touch,
            prior_m5=prior,
            direction=direction,
            low=float(zone.low),
            high=float(zone.high),
            atr=atr,
        )

        # If the entire 0.50 ATR reaction already occurred inside the touch
        # bar, the gate is too late to authorize a fresh next-bar entry.
        if (
            touch_meta["touch_favorable_excursion_atr"]
            + 1e-12
            >= REACTION_ATR
        ):
            continue

        outcome = evaluate_future_outcome(
            m5,
            touch_index=touch_index,
            direction=direction,
            zone_low=float(zone.low),
            zone_high=float(zone.high),
            atr_points=atr,
        )
        if outcome.status == "PENDING":
            continue

        features = tuple(pre_features) + tuple(touch_features)
        if len(features) != len(FEATURE_NAMES):
            raise ValueError("V179_FEATURE_CONTRACT")
        if not all(isfinite(value) for value in features):
            raise ValueError("V179_FEATURE_NONFINITE")

        output.append(
            Episode(
                zone_id=_stable_zone_id(zone),
                direction=direction,
                available_at=available_at,
                touch_at=ensure_utc(touch.timestamp),
                decision_at=decision_at,
                zone_low=float(zone.low),
                zone_high=float(zone.high),
                features=features,
                touch_reclaim_atr=float(touch_meta["reclaim_atr"]),
                touch_rejection_wick_fraction=float(
                    touch_meta["rejection_wick_fraction"]
                ),
                touch_penetration_atr=float(
                    touch_meta["penetration_atr"]
                ),
                touch_favorable_close=bool(
                    touch_meta["favorable_close"]
                ),
                outcome=outcome,
            )
        )

    output.sort(key=lambda row: (row.touch_at, row.zone_id))
    return tuple(output)


def fit_logistic_model(
    episodes: Sequence[Episode],
) -> LogisticModel:
    if len(episodes) < MIN_TRAIN_PER_DIRECTION:
        raise ValueError(f"V179_TRAIN_SAMPLE_INSUFFICIENT:{len(episodes)}")
    matrix = np.asarray([episode.features for episode in episodes], dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(FEATURE_NAMES)
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("V179_FEATURE_MATRIX_INVALID")

    labels = np.asarray(
        [float(episode.outcome.label_hold) for episode in episodes],
        dtype=float,
    )
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    normalized = np.clip((matrix - means) / scales, -8.0, 8.0)

    coefficients = np.zeros(normalized.shape[1], dtype=float)
    positive_rate = float(np.mean(labels))
    clipped = min(1.0 - 1e-6, max(1e-6, positive_rate))
    intercept = float(np.log(clipped / (1.0 - clipped)))

    for _ in range(LOGISTIC_ITERATIONS):
        logits = np.clip(
            normalized @ coefficients + intercept,
            -30.0,
            30.0,
        )
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = probabilities - labels
        gradient = (
            normalized.T @ errors / len(labels)
            + LOGISTIC_L2 * coefficients / len(labels)
        )
        coefficients -= LOGISTIC_LEARNING_RATE * gradient
        intercept -= LOGISTIC_LEARNING_RATE * float(np.mean(errors))

    return LogisticModel(
        feature_names=FEATURE_NAMES,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        positive_rate=positive_rate,
        rows=len(episodes),
    )


def predict_probability(
    model: LogisticModel,
    features: Sequence[float],
) -> float:
    vector = np.asarray(tuple(features), dtype=float)
    means = np.asarray(model.means, dtype=float)
    scales = np.asarray(model.scales, dtype=float)
    coefficients = np.asarray(model.coefficients, dtype=float)
    normalized = np.clip((vector - means) / scales, -8.0, 8.0)
    logit = float(
        np.clip(
            normalized @ coefficients + model.intercept,
            -30.0,
            30.0,
        )
    )
    return float(1.0 / (1.0 + np.exp(-logit)))


def score_episodes(
    episodes: Sequence[Episode],
    *,
    model: LogisticModel,
) -> tuple[ScoredEpisode, ...]:
    return tuple(
        ScoredEpisode(
            episode=episode,
            probability_hold=predict_probability(model, episode.features),
        )
        for episode in episodes
    )


def _split_chronological(
    episodes: Sequence[Episode],
) -> tuple[
    tuple[Episode, ...],
    tuple[Episode, ...],
    tuple[Episode, ...],
]:
    rows = tuple(sorted(episodes, key=lambda row: row.touch_at))
    times = sorted({row.touch_at for row in rows})
    if len(times) < 20:
        return (), (), ()

    calibration_index = int(len(times) * TRAIN_FRACTION)
    holdout_index = int(
        len(times) * (TRAIN_FRACTION + CALIBRATION_FRACTION)
    )
    if (
        calibration_index <= 0
        or holdout_index <= calibration_index
        or holdout_index >= len(times)
    ):
        return (), (), ()

    calibration_start = times[calibration_index]
    holdout_start = times[holdout_index]
    purge = timedelta(hours=PURGE_HOURS)

    train = tuple(
        row
        for row in rows
        if row.touch_at < calibration_start - purge
    )
    calibration = tuple(
        row
        for row in rows
        if calibration_start <= row.touch_at < holdout_start - purge
    )
    holdout = tuple(row for row in rows if row.touch_at >= holdout_start)
    return train, calibration, holdout


def _walk_forward_splits(
    episodes: Sequence[Episode],
) -> tuple[
    tuple[tuple[Episode, ...], tuple[Episode, ...]],
    ...,
]:
    rows = tuple(sorted(episodes, key=lambda row: row.touch_at))
    times = sorted({row.touch_at for row in rows})
    if len(times) < 20:
        return ()
    purge = timedelta(hours=PURGE_HOURS)
    folds = []
    for train_fraction, validation_fraction in (
        (0.35, 0.45),
        (0.45, 0.55),
        (0.55, 0.65),
    ):
        train_index = int(len(times) * train_fraction)
        validation_end_index = int(len(times) * validation_fraction)
        if train_index <= 0 or validation_end_index <= train_index:
            continue
        validation_start = times[train_index]
        validation_end = times[min(validation_end_index, len(times) - 1)]
        train = tuple(
            row
            for row in rows
            if row.touch_at < validation_start - purge
        )
        validation = tuple(
            row
            for row in rows
            if validation_start <= row.touch_at < validation_end
        )
        if train and validation:
            folds.append((train, validation))
    return tuple(folds)


def _brier(
    scored: Sequence[ScoredEpisode],
) -> float | None:
    if not scored:
        return None
    return float(
        np.mean(
            [
                (
                    row.probability_hold
                    - float(row.episode.outcome.label_hold)
                )
                ** 2
                for row in scored
            ]
        )
    )


def _status_counts(
    rows: Sequence[Episode],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.outcome.status] = counts.get(row.outcome.status, 0) + 1
    return counts


def _threshold_metrics(
    scored: Sequence[ScoredEpisode],
    *,
    threshold: float,
) -> dict[str, Any]:
    selected = [
        row
        for row in scored
        if row.probability_hold >= float(threshold)
    ]
    holds = sum(row.episode.outcome.label_hold for row in selected)
    breaks = sum(row.episode.outcome.status == "BREAK" for row in selected)
    stalls = sum(row.episode.outcome.status == "STALL" for row in selected)
    return {
        "threshold": float(threshold),
        "universe": len(scored),
        "selected": len(selected),
        "coverage": None if not scored else len(selected) / len(scored),
        "holds": int(holds),
        "breaks": int(breaks),
        "stalls": int(stalls),
        "precision_hold": None if not selected else holds / len(selected),
        "wilson_lower_95": wilson_lower_bound(int(holds), len(selected)),
        "mean_probability": None
        if not selected
        else float(np.mean([row.probability_hold for row in selected])),
    }


def _calibrate_threshold(
    scored: Sequence[ScoredEpisode],
) -> tuple[float | None, dict[str, Any]]:
    candidates = []
    for threshold in THRESHOLD_GRID:
        metrics = _threshold_metrics(scored, threshold=threshold)
        if metrics["selected"] < MIN_CALIBRATION_SELECTED_PER_DIRECTION:
            continue
        if (metrics["coverage"] or 0.0) < MIN_CALIBRATION_COVERAGE:
            continue
        candidates.append(metrics)
    if not candidates:
        return None, {
            "selection_reason": "NO_THRESHOLD_MEETS_SAMPLE_FLOOR",
            "minimum_selected": MIN_CALIBRATION_SELECTED_PER_DIRECTION,
            "calibration_universe": len(scored),
        }
    best = max(
        candidates,
        key=lambda row: (
            float(row["wilson_lower_95"] or 0.0),
            float(row["precision_hold"] or 0.0),
            float(row["coverage"] or 0.0),
        ),
    )
    return float(best["threshold"]), best | {
        "selection_reason": "MAX_WILSON_SUBJECT_TO_SAMPLE_FLOOR",
    }


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
            for name, coefficient in ranked[:18]
        ],
    }


def _fixed_rule_metrics(
    rows: Sequence[Episode],
) -> dict[str, Any]:
    def summarize(selected: Sequence[Episode]) -> dict[str, Any]:
        holds = sum(row.outcome.label_hold for row in selected)
        return {
            "selected": len(selected),
            "holds": int(holds),
            "precision_hold": None
            if not selected
            else holds / len(selected),
            "wilson_lower_95": wilson_lower_bound(
                int(holds),
                len(selected),
            ),
        }

    return {
        "reclaim_outside_zone": summarize(
            [row for row in rows if row.touch_reclaim_atr >= 0.0]
        ),
        "reclaim_plus_rejection_wick_25": summarize(
            [
                row
                for row in rows
                if row.touch_reclaim_atr >= 0.0
                and row.touch_rejection_wick_fraction >= 0.25
            ]
        ),
        "favorable_close_plus_rejection_wick_25": summarize(
            [
                row
                for row in rows
                if row.touch_favorable_close
                and row.touch_rejection_wick_fraction >= 0.25
            ]
        ),
        "deep_penetration_then_reclaim": summarize(
            [
                row
                for row in rows
                if row.touch_penetration_atr >= 0.15
                and row.touch_reclaim_atr >= 0.0
            ]
        ),
    }


def _walk_forward_report(
    episodes: Sequence[Episode],
) -> dict[str, Any]:
    output: dict[str, list[dict[str, Any]]] = {"LONG": [], "SHORT": []}
    for fold_index, (train, validation) in enumerate(
        _walk_forward_splits(episodes),
        start=1,
    ):
        for direction in ("LONG", "SHORT"):
            d_train = tuple(
                row for row in train if row.direction == direction
            )
            d_validation = tuple(
                row for row in validation if row.direction == direction
            )
            if (
                len(d_train) < MIN_TRAIN_PER_DIRECTION
                or len(d_validation) < 20
            ):
                output[direction].append(
                    {
                        "fold": fold_index,
                        "status": "INSUFFICIENT_DIRECTION_SAMPLE",
                        "train": len(d_train),
                        "validation": len(d_validation),
                    }
                )
                continue
            model = fit_logistic_model(d_train)
            scored = score_episodes(d_validation, model=model)
            median_threshold = float(
                np.median([row.probability_hold for row in scored])
            )
            output[direction].append(
                {
                    "fold": fold_index,
                    "status": "EVALUATED",
                    "train": len(d_train),
                    "validation": len(d_validation),
                    "base_hold_rate": float(
                        np.mean(
                            [
                                row.episode.outcome.label_hold
                                for row in scored
                            ]
                        )
                    ),
                    "brier": _brier(scored),
                    "above_median": _threshold_metrics(
                        scored,
                        threshold=median_threshold,
                    ),
                }
            )
    return output


def evaluate_research(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> dict[str, Any]:
    episodes = build_episodes(m15_bars, m5_bars)
    train, calibration, holdout = _split_chronological(episodes)

    base = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "data_provenance": {
            "structure": "CTRADER_M15_TO_H1_H4_D1_RESAMPLE",
            "microstructure": "CTRADER_HISTORICAL_M5_TRENDBAR_OHLC_TICK_COUNT",
            "historical_spread_features": "EXCLUDED_UNAVAILABLE",
        },
        "label_contract": {
            "population": (
                "UNIQUE_H1_ORIGIN_FIRST_M5_TOUCH_WITHIN_48H_"
                "TOUCH_BAR_NOT_INVALIDATED_AND_NOT_ALREADY_0.50ATR_REACTED"
            ),
            "decision_time": "COMPLETED_FIRST_TOUCH_M5_CLOSE",
            "hold": (
                "NEXT_48_M5_REACH_0.50_ATR_FAVORABLE_EXCURSION_"
                "BEFORE_INVALIDATION"
            ),
            "break": "FUTURE_M5_CLOSE_BEYOND_ZONE_BEFORE_HOLD",
            "stall": "NEITHER_HOLD_NOR_BREAK_WITHIN_NEXT_48_M5",
            "touch_bar_features_used": True,
            "future_after_decision_features_used": False,
        },
        "episodes": len(episodes),
        "status_counts": _status_counts(episodes),
        "split": {
            "train": len(train),
            "calibration": len(calibration),
            "holdout": len(holdout),
            "train_fraction": TRAIN_FRACTION,
            "calibration_fraction": CALIBRATION_FRACTION,
            "holdout_fraction": HOLDOUT_FRACTION,
            "purge_hours": PURGE_HOURS,
        },
        "features": list(FEATURE_NAMES),
        "walk_forward": _walk_forward_report(episodes),
    }

    if min(len(train), len(calibration), len(holdout)) <= 0:
        return base | {"decision": "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT"}

    results: dict[str, Any] = {}
    passed_directions = []

    for direction in ("LONG", "SHORT"):
        d_train = tuple(row for row in train if row.direction == direction)
        d_calibration = tuple(
            row for row in calibration if row.direction == direction
        )
        d_holdout = tuple(
            row for row in holdout if row.direction == direction
        )

        if (
            len(d_train) < MIN_TRAIN_PER_DIRECTION
            or len(d_calibration)
            < MIN_CALIBRATION_SELECTED_PER_DIRECTION
            or len(d_holdout) < MIN_CLAIM_PER_DIRECTION
        ):
            results[direction] = {
                "decision": "INSUFFICIENT_DIRECTION_SAMPLE",
                "population": {
                    "train": len(d_train),
                    "calibration": len(d_calibration),
                    "holdout": len(d_holdout),
                },
                "fixed_rules_holdout": _fixed_rule_metrics(d_holdout),
            }
            passed_directions.append(False)
            continue

        model = fit_logistic_model(d_train)
        calibration_scored = score_episodes(
            d_calibration,
            model=model,
        )
        threshold, calibration_report = _calibrate_threshold(
            calibration_scored
        )
        holdout_scored = score_episodes(d_holdout, model=model)

        if threshold is None:
            holdout_report = {
                "threshold": None,
                "universe": len(holdout_scored),
                "selected": 0,
                "coverage": 0.0,
                "holds": 0,
                "breaks": 0,
                "stalls": 0,
                "precision_hold": None,
                "wilson_lower_95": None,
                "mean_probability": None,
            }
            passed = False
        else:
            holdout_report = _threshold_metrics(
                holdout_scored,
                threshold=threshold,
            )
            passed = bool(
                holdout_report["selected"] >= MIN_CLAIM_PER_DIRECTION
                and (holdout_report["precision_hold"] or 0.0)
                >= CLAIM_PRECISION
                and (holdout_report["wilson_lower_95"] or 0.0)
                >= CLAIM_PRECISION
            )

        results[direction] = {
            "decision": (
                "DIRECTION_GATE_MET"
                if passed
                else "DIRECTION_GATE_NOT_MET"
            ),
            "population": {
                "train": len(d_train),
                "calibration": len(d_calibration),
                "holdout": len(d_holdout),
            },
            "status_counts": {
                "train": _status_counts(d_train),
                "calibration": _status_counts(d_calibration),
                "holdout": _status_counts(d_holdout),
            },
            "model": _model_payload(model),
            "calibration_brier": _brier(calibration_scored),
            "calibration_threshold": calibration_report,
            "holdout_brier": _brier(holdout_scored),
            "untouched_holdout": holdout_report,
            "fixed_rules_holdout": _fixed_rule_metrics(d_holdout),
            "claim_gate_passed": passed,
        }
        passed_directions.append(passed)

    claim_passed = all(passed_directions) and len(passed_directions) == 2
    return base | {
        "directions": results,
        "claim_gate": {
            "target_precision": CLAIM_PRECISION,
            "minimum_selected_per_direction": MIN_CLAIM_PER_DIRECTION,
            "requires_wilson_lower_95_at_target": True,
            "passed": claim_passed,
        },
        "decision": (
            "RESEARCH_TARGET_MET"
            if claim_passed
            else "REJECT_80_PERCENT_NOT_PROVEN"
        ),
        "notes": [
            "V179 is a post-touch reaction admission research gate, not a pre-touch destination forecast.",
            "The touch M5 bar is completed before any V179 decision; labels start from the next M5 bar.",
            "Touch bars already invalidated or already completing the full 0.50 ATR reaction are excluded because no fresh next-bar entry remains.",
            "V175 remains the pre-touch destination model; V179 tests whether completed micro reaction evidence can improve conditional reversal precision.",
            "No V179 output has AFIC admission, sizing, risk, or broker execution authority.",
        ],
    }

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import cos, isfinite, pi, sin
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_afic_path_shadow_observer import (
    OriginZone,
    _atr,
    _origin_zones,
    _resample_completed,
    _stable_zone_id,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_H1_ORIGIN_HOLD_BREAK_V177"
ARTIFACT_CONTRACT = "XAU_H1_ORIGIN_HOLD_BREAK_V177_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

MAX_ZONE_AGE_HOURS = 48
HOLD_REACTION_ATR = 0.50
HOLD_HORIZON_M15 = 16
PURGE_HOURS = 48
CLAIM_PRECISION = 0.80
MIN_CLAIM_PER_DIRECTION = 100
MIN_TRAIN_PER_DIRECTION = 80
MIN_CALIBRATION_SELECTED_PER_DIRECTION = 75
MIN_CALIBRATION_COVERAGE = 0.05
TRAIN_FRACTION = 0.50
CALIBRATION_FRACTION = 0.20
HOLDOUT_FRACTION = 0.30
LOGISTIC_ITERATIONS = 1200
LOGISTIC_LEARNING_RATE = 0.035
LOGISTIC_L2 = 0.15
THRESHOLD_GRID = tuple(round(value, 2) for value in np.arange(0.35, 0.91, 0.05))

SESSION_WINDOWS = {
    "ASIA": (0, 8),
    "LONDON": (8, 13),
    "NEW_YORK": (13, 21),
}

FEATURE_NAMES = (
    "zone_width_atr",
    "zone_age_hours_norm",
    "origin_age_hours_norm",
    "displacement_range_atr",
    "displacement_body_fraction",
    "distance_pre_touch_atr",
    "approach_efficiency_8",
    "approach_net_atr_8",
    "approach_body_pressure_atr_8",
    "approach_range_atr_8",
    "approach_speed_atr_4",
    "toward_bar_fraction_8",
    "tick_last_to_mean16",
    "tick_mean4_to_mean16",
    "tick_mean4_to_mean64",
    "tick_trend_4v16",
    "spread_avg4_atr",
    "spread_max4_atr",
    "spread_avg4_to_avg16",
    "spread_max4_to_max16",
    "m15_range4_to_range16",
    "m15_volatility16_to64",
    "h4_trend_alignment",
    "h4_close_ema20_alignment",
    "h4_volatility_ratio",
    "d1_trend_alignment",
    "d1_close_ema20_alignment",
    "d1_volatility_ratio",
    "hour_sin",
    "hour_cos",
    "session_asia",
    "session_london",
    "session_new_york",
    "session_other",
    "freshness_x_displacement",
    "approach_speed_x_distance",
    "h4_x_d1_alignment",
    "activity_x_spread",
    "volatility_x_pressure",
    "displacement_x_body_fraction",
)


@dataclass(frozen=True, slots=True)
class HoldBreakOutcome:
    status: str
    label_hold: bool
    touch_at: datetime
    outcome_at: datetime | None
    bars_to_outcome: int | None
    max_favorable_excursion_atr: float


@dataclass(frozen=True, slots=True)
class HoldBreakEpisode:
    zone_id: str
    direction: str
    available_at: datetime
    touch_at: datetime
    decision_at: datetime
    zone_low: float
    zone_high: float
    features: tuple[float, ...]
    outcome: HoldBreakOutcome


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
    episode: HoldBreakEpisode
    probability_hold: float


def _touch(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(row: Bar, *, low: float, high: float, direction: str) -> bool:
    if direction == "SHORT":
        return float(row.close) > high
    return float(row.close) < low


def _favorable_excursion(
    row: Bar,
    *,
    low: float,
    high: float,
    direction: str,
) -> float:
    if direction == "LONG":
        return max(0.0, float(row.high) - high)
    return max(0.0, low - float(row.low))


def evaluate_hold_break_outcome(
    bars: Sequence[Bar],
    *,
    touch_index: int,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
    horizon_m15: int = HOLD_HORIZON_M15,
    reaction_atr: float = HOLD_REACTION_ATR,
) -> HoldBreakOutcome:
    rows = tuple(bars)
    normalized = str(direction).upper().strip()
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if not (0 <= touch_index < len(rows)):
        raise ValueError("touch_index out of range")
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("zone bounds must be finite and ordered")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_points must be positive and finite")

    touch_at = ensure_utc(rows[touch_index].timestamp)
    touch_row = rows[touch_index]
    if _invalidated(
        touch_row,
        low=low,
        high=high,
        direction=normalized,
    ):
        return HoldBreakOutcome(
            status="BREAK_TOUCH_BAR",
            label_hold=False,
            touch_at=touch_at,
            outcome_at=touch_at,
            bars_to_outcome=0,
            max_favorable_excursion_atr=0.0,
        )

    future = rows[touch_index + 1 : touch_index + 1 + int(horizon_m15)]
    max_excursion = 0.0
    for offset, row in enumerate(future, start=1):
        excursion = _favorable_excursion(
            row,
            low=low,
            high=high,
            direction=normalized,
        )
        max_excursion = max(max_excursion, excursion)

        # Break wins same-bar ambiguity. This is deliberately conservative.
        if _invalidated(
            row,
            low=low,
            high=high,
            direction=normalized,
        ):
            return HoldBreakOutcome(
                status="BREAK",
                label_hold=False,
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )

        if max_excursion + 1e-12 >= float(reaction_atr) * atr:
            return HoldBreakOutcome(
                status="HOLD",
                label_hold=True,
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )

    if len(future) < int(horizon_m15):
        return HoldBreakOutcome(
            status="PENDING",
            label_hold=False,
            touch_at=touch_at,
            outcome_at=None,
            bars_to_outcome=None,
            max_favorable_excursion_atr=max_excursion / atr,
        )

    return HoldBreakOutcome(
        status="STALL",
        label_hold=False,
        touch_at=touch_at,
        outcome_at=ensure_utc(future[-1].timestamp),
        bars_to_outcome=int(horizon_m15),
        max_favorable_excursion_atr=max_excursion / atr,
    )


def _frame_times(frame: pd.DataFrame) -> tuple[datetime, ...]:
    return tuple(ensure_utc(value.to_pydatetime()) for value in frame["time"])


def _last_frame_row(
    frame: pd.DataFrame,
    timestamp: datetime,
    *,
    times: Sequence[datetime],
):
    if frame.empty:
        return None
    index = bisect_right(times, ensure_utc(timestamp)) - 1
    return None if index < 0 else frame.iloc[index]


def _frame_trend_context(
    frame: pd.DataFrame,
    *,
    timestamp: datetime,
    times: Sequence[datetime],
    direction: str,
) -> tuple[float, float, float]:
    if frame.empty:
        return 0.0, 0.0, 1.0
    index = bisect_right(times, ensure_utc(timestamp)) - 1
    if index < 0:
        return 0.0, 0.0, 1.0
    row = frame.iloc[index]
    atr14 = float(row.get("atr14", np.nan))
    if not isfinite(atr14) or atr14 <= 0:
        return 0.0, 0.0, 1.0
    lag_index = max(0, index - 3)
    close = float(row["close"])
    lag_close = float(frame.iloc[lag_index]["close"])
    reversal_sign = 1.0 if direction == "LONG" else -1.0
    trend = reversal_sign * (close - lag_close) / atr14
    ema20 = float(row.get("ema20", close))
    if not isfinite(ema20):
        ema20 = close
    ema_alignment = reversal_sign * (close - ema20) / atr14
    atr5 = float(row.get("atr5", atr14))
    atr20 = float(row.get("atr20", atr14))
    if not isfinite(atr5) or atr5 <= 0:
        atr5 = atr14
    if not isfinite(atr20) or atr20 <= 0:
        atr20 = atr14
    volatility_ratio = atr5 / max(atr20, 1e-12)
    return (
        float(np.clip(trend, -6.0, 6.0)),
        float(np.clip(ema_alignment, -6.0, 6.0)),
        float(np.clip(volatility_ratio, 0.0, 5.0)),
    )


def _true_ranges(rows: Sequence[Bar]) -> np.ndarray:
    if not rows:
        return np.asarray([], dtype=float)
    values: list[float] = []
    previous_close = float(rows[0].close)
    for row in rows:
        high = float(row.high)
        low = float(row.low)
        values.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
        previous_close = float(row.close)
    return np.asarray(values, dtype=float)


def _safe_ratio(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    if not isfinite(numerator) or not isfinite(denominator) or abs(denominator) < 1e-12:
        return default
    return float(numerator / denominator)


def _distance_to_zone(
    price: float,
    *,
    low: float,
    high: float,
    direction: str,
) -> float:
    if direction == "SHORT":
        return max(0.0, low - price)
    return max(0.0, price - high)


def _session_features(timestamp: datetime) -> tuple[float, float, float, float]:
    hour = ensure_utc(timestamp).hour
    asia = float(SESSION_WINDOWS["ASIA"][0] <= hour < SESSION_WINDOWS["ASIA"][1])
    london = float(
        SESSION_WINDOWS["LONDON"][0] <= hour < SESSION_WINDOWS["LONDON"][1]
    )
    new_york = float(
        SESSION_WINDOWS["NEW_YORK"][0] <= hour < SESSION_WINDOWS["NEW_YORK"][1]
    )
    other = float(not (asia or london or new_york))
    return asia, london, new_york, other


def _feature_vector(
    *,
    zone: OriginZone,
    prior: Sequence[Bar],
    decision_at: datetime,
    h4: pd.DataFrame,
    h4_times: Sequence[datetime],
    daily: pd.DataFrame,
    daily_times: Sequence[datetime],
) -> tuple[float, ...]:
    if len(prior) < 64:
        raise ValueError("at least 64 pre-touch M15 bars are required")
    atr = float(zone.h1_atr)
    if not isfinite(atr) or atr <= 0:
        raise ValueError("zone h1_atr must be positive")

    direction = str(zone.direction)
    low = float(zone.low)
    high = float(zone.high)
    last = prior[-1]
    prior4 = prior[-4:]
    prior8 = prior[-8:]
    prior16 = prior[-16:]
    prior64 = prior[-64:]

    closes8 = [float(row.close) for row in prior8]
    total_path8 = sum(
        abs(right - left)
        for left, right in zip(closes8, closes8[1:])
    )
    toward_sign = 1.0 if direction == "SHORT" else -1.0
    net8 = toward_sign * (closes8[-1] - closes8[0])
    approach_efficiency = 0.0 if total_path8 <= 0 else net8 / total_path8
    body_pressure = sum(
        toward_sign * (float(row.close) - float(row.open))
        for row in prior8
    ) / atr
    approach_range = (
        max(float(row.high) for row in prior8)
        - min(float(row.low) for row in prior8)
    ) / atr
    toward_fraction = float(
        np.mean(
            [
                toward_sign * (float(row.close) - float(row.open)) > 0
                for row in prior8
            ]
        )
    )

    distance_now = _distance_to_zone(
        float(last.close),
        low=low,
        high=high,
        direction=direction,
    )
    distance_4ago = _distance_to_zone(
        float(prior4[0].close),
        low=low,
        high=high,
        direction=direction,
    )
    approach_speed = (distance_4ago - distance_now) / atr

    ticks4 = np.asarray([float(row.tick_count) for row in prior4], dtype=float)
    ticks16 = np.asarray([float(row.tick_count) for row in prior16], dtype=float)
    ticks64 = np.asarray([float(row.tick_count) for row in prior64], dtype=float)
    mean_tick16 = float(np.mean(ticks16))
    tick_last_ratio = _safe_ratio(float(last.tick_count), mean_tick16, default=1.0)
    tick_4_16 = _safe_ratio(float(np.mean(ticks4)), mean_tick16, default=1.0)
    tick_4_64 = _safe_ratio(
        float(np.mean(ticks4)),
        float(np.mean(ticks64)),
        default=1.0,
    )
    tick_trend = _safe_ratio(
        float(np.mean(ticks4) - np.mean(ticks16[:4])),
        mean_tick16,
        default=0.0,
    )

    spread_avg4 = float(np.mean([float(row.spread_avg) for row in prior4]))
    spread_avg16 = float(np.mean([float(row.spread_avg) for row in prior16]))
    spread_max4 = float(max(float(row.spread_max) for row in prior4))
    spread_max16 = float(max(float(row.spread_max) for row in prior16))
    spread_avg_ratio = _safe_ratio(spread_avg4, spread_avg16, default=1.0)
    spread_max_ratio = _safe_ratio(spread_max4, spread_max16, default=1.0)

    ranges4 = np.asarray(
        [float(row.high) - float(row.low) for row in prior4],
        dtype=float,
    )
    ranges16 = np.asarray(
        [float(row.high) - float(row.low) for row in prior16],
        dtype=float,
    )
    range_ratio = _safe_ratio(
        float(np.mean(ranges4)),
        float(np.mean(ranges16)),
        default=1.0,
    )
    tr16 = _true_ranges(prior16)
    tr64 = _true_ranges(prior64)
    volatility_ratio = _safe_ratio(
        float(np.mean(tr16)),
        float(np.mean(tr64)),
        default=1.0,
    )

    h4_trend, h4_ema, h4_vol = _frame_trend_context(
        h4,
        timestamp=decision_at,
        times=h4_times,
        direction=direction,
    )
    d1_trend, d1_ema, d1_vol = _frame_trend_context(
        daily,
        timestamp=decision_at,
        times=daily_times,
        direction=direction,
    )

    age_hours = max(
        0.0,
        (ensure_utc(decision_at) - ensure_utc(zone.available_at)).total_seconds()
        / 3600.0,
    )
    origin_age_hours = max(
        0.0,
        (ensure_utc(decision_at) - ensure_utc(zone.origin_at)).total_seconds()
        / 3600.0,
    )
    hour_value = decision_at.hour + decision_at.minute / 60.0
    hour_angle = 2.0 * pi * hour_value / 24.0
    asia, london, new_york, other = _session_features(decision_at)

    zone_width_atr = (high - low) / atr
    age_norm = min(1.0, age_hours / MAX_ZONE_AGE_HOURS)
    origin_age_norm = min(2.0, origin_age_hours / MAX_ZONE_AGE_HOURS)
    displacement_range = float(zone.displacement_range_atr)
    displacement_body = float(zone.displacement_body_fraction)
    distance_atr = distance_now / atr
    approach_net_atr = net8 / atr
    spread_avg4_atr = spread_avg4 / atr
    spread_max4_atr = spread_max4 / atr

    values = [
        zone_width_atr,
        age_norm,
        origin_age_norm,
        displacement_range,
        displacement_body,
        distance_atr,
        float(np.clip(approach_efficiency, -1.0, 1.0)),
        float(np.clip(approach_net_atr, -6.0, 6.0)),
        float(np.clip(body_pressure, -6.0, 6.0)),
        float(np.clip(approach_range, 0.0, 8.0)),
        float(np.clip(approach_speed, -6.0, 6.0)),
        toward_fraction,
        float(np.clip(tick_last_ratio, 0.0, 6.0)),
        float(np.clip(tick_4_16, 0.0, 6.0)),
        float(np.clip(tick_4_64, 0.0, 6.0)),
        float(np.clip(tick_trend, -4.0, 4.0)),
        float(np.clip(spread_avg4_atr, 0.0, 2.0)),
        float(np.clip(spread_max4_atr, 0.0, 4.0)),
        float(np.clip(spread_avg_ratio, 0.0, 6.0)),
        float(np.clip(spread_max_ratio, 0.0, 6.0)),
        float(np.clip(range_ratio, 0.0, 6.0)),
        float(np.clip(volatility_ratio, 0.0, 6.0)),
        h4_trend,
        h4_ema,
        h4_vol,
        d1_trend,
        d1_ema,
        d1_vol,
        sin(hour_angle),
        cos(hour_angle),
        asia,
        london,
        new_york,
        other,
        age_norm * displacement_range,
        float(np.clip(approach_speed * distance_atr, -12.0, 12.0)),
        float(np.clip(h4_trend * d1_trend, -12.0, 12.0)),
        float(np.clip(tick_4_16 * spread_avg_ratio, 0.0, 12.0)),
        float(np.clip(volatility_ratio * body_pressure, -12.0, 12.0)),
        displacement_range * displacement_body,
    ]
    if len(values) != len(FEATURE_NAMES):
        raise ValueError(
            f"feature contract mismatch:{len(values)}!={len(FEATURE_NAMES)}"
        )
    bad = [
        FEATURE_NAMES[index]
        for index, value in enumerate(values)
        if not isfinite(float(value))
    ]
    if bad:
        raise ValueError(f"nonfinite features:{','.join(bad)}")
    return tuple(float(value) for value in values)


def build_hold_break_episodes(
    bars: Sequence[Bar],
) -> tuple[HoldBreakEpisode, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 5_000:
        return ()
    row_times = tuple(ensure_utc(row.timestamp) for row in rows)
    last_closed_at = row_times[-1] + timedelta(minutes=15)

    h4 = _resample_completed(rows, "4h", as_of=last_closed_at)
    h4["ema20"] = h4["close"].ewm(span=20, adjust=False).mean()
    h4["atr14"] = _atr(h4, 14)
    h4["atr5"] = _atr(h4, 5)
    h4["atr20"] = _atr(h4, 20)

    daily = _resample_completed(rows, "1D", as_of=last_closed_at)
    daily["ema20"] = daily["close"].ewm(span=20, adjust=False).mean()
    daily["atr14"] = _atr(daily, 14)
    daily["atr5"] = _atr(daily, 5)
    daily["atr20"] = _atr(daily, 20)

    h4_times = _frame_times(h4)
    daily_times = _frame_times(daily)
    zones = _origin_zones(rows, as_of=last_closed_at)
    episodes: list[HoldBreakEpisode] = []

    for zone in zones:
        direction = str(zone.direction).upper()
        if direction not in {"LONG", "SHORT"}:
            continue
        atr = float(zone.h1_atr)
        if not isfinite(atr) or atr <= 0:
            continue

        available_at = ensure_utc(zone.available_at)
        start_index = bisect_right(
            row_times,
            available_at - timedelta(microseconds=1),
        )
        end_at = available_at + timedelta(hours=MAX_ZONE_AGE_HOURS)
        end_index = min(
            len(rows),
            bisect_right(row_times, end_at),
        )
        if start_index >= end_index:
            continue

        touch_index: int | None = None
        for index in range(start_index, end_index):
            row = rows[index]
            if _touch(
                row,
                low=float(zone.low),
                high=float(zone.high),
            ):
                touch_index = index
                break
        if touch_index is None or touch_index < 64:
            continue

        decision_index = touch_index - 1
        decision_at = ensure_utc(rows[decision_index].timestamp) + timedelta(minutes=15)
        prior = rows[decision_index - 63 : decision_index + 1]
        if len(prior) < 64:
            continue

        outcome = evaluate_hold_break_outcome(
            rows,
            touch_index=touch_index,
            direction=direction,
            zone_low=float(zone.low),
            zone_high=float(zone.high),
            atr_points=atr,
        )
        if outcome.status == "PENDING":
            continue

        features = _feature_vector(
            zone=zone,
            prior=prior,
            decision_at=decision_at,
            h4=h4,
            h4_times=h4_times,
            daily=daily,
            daily_times=daily_times,
        )
        episodes.append(
            HoldBreakEpisode(
                zone_id=_stable_zone_id(zone),
                direction=direction,
                available_at=available_at,
                touch_at=outcome.touch_at,
                decision_at=decision_at,
                zone_low=float(zone.low),
                zone_high=float(zone.high),
                features=features,
                outcome=outcome,
            )
        )

    episodes.sort(key=lambda row: (row.touch_at, row.zone_id))
    return tuple(episodes)


def fit_logistic_model(
    episodes: Sequence[HoldBreakEpisode],
) -> LogisticModel:
    if len(episodes) < MIN_TRAIN_PER_DIRECTION:
        raise ValueError(f"insufficient training rows:{len(episodes)}")
    matrix = np.asarray([episode.features for episode in episodes], dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_NAMES):
        raise ValueError("feature matrix contract mismatch")
    if not np.isfinite(matrix).all():
        raise ValueError("nonfinite feature matrix")
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
    clipped_rate = min(1.0 - 1e-6, max(1e-6, positive_rate))
    intercept = float(np.log(clipped_rate / (1.0 - clipped_rate)))

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
        feature_names=FEATURE_NAMES,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        positive_rate=positive_rate,
        rows=len(episodes),
    )


def predict_probability(model: LogisticModel, features: Sequence[float]) -> float:
    vector = np.asarray(tuple(features), dtype=float)
    means = np.asarray(model.means, dtype=float)
    scales = np.asarray(model.scales, dtype=float)
    coefficients = np.asarray(model.coefficients, dtype=float)
    normalized = np.clip((vector - means) / scales, -8.0, 8.0)
    logit_value = float(
        np.clip(normalized @ coefficients + model.intercept, -30.0, 30.0)
    )
    return float(1.0 / (1.0 + np.exp(-logit_value)))


def score_episodes(
    episodes: Sequence[HoldBreakEpisode],
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
    episodes: Sequence[HoldBreakEpisode],
) -> tuple[
    tuple[HoldBreakEpisode, ...],
    tuple[HoldBreakEpisode, ...],
    tuple[HoldBreakEpisode, ...],
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
    episodes: Sequence[HoldBreakEpisode],
) -> tuple[
    tuple[
        tuple[HoldBreakEpisode, ...],
        tuple[HoldBreakEpisode, ...],
    ],
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


def _brier(scored: Sequence[ScoredEpisode]) -> float | None:
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


def _status_counts(rows: Sequence[HoldBreakEpisode]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.outcome.status)
        counts[status] = counts.get(status, 0) + 1
    return counts


def _threshold_metrics(
    scored: Sequence[ScoredEpisode],
    *,
    threshold: float,
) -> dict[str, Any]:
    selected = [
        row for row in scored if row.probability_hold >= float(threshold)
    ]
    hits = sum(row.episode.outcome.label_hold for row in selected)
    breaks = sum(
        row.episode.outcome.status.startswith("BREAK")
        for row in selected
    )
    stalls = sum(row.episode.outcome.status == "STALL" for row in selected)
    return {
        "threshold": float(threshold),
        "universe": len(scored),
        "selected": len(selected),
        "coverage": None if not scored else len(selected) / len(scored),
        "holds": int(hits),
        "breaks": int(breaks),
        "stalls": int(stalls),
        "precision_hold": None if not selected else hits / len(selected),
        "wilson_lower_95": wilson_lower_bound(int(hits), len(selected)),
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
            "minimum_coverage": MIN_CALIBRATION_COVERAGE,
            "calibration_universe": len(scored),
            "projected_holdout_sample_floor": MIN_CLAIM_PER_DIRECTION,
            "calibration_to_holdout_ratio": (
                HOLDOUT_FRACTION / CALIBRATION_FRACTION
            ),
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
        "projected_holdout_sample_floor": MIN_CLAIM_PER_DIRECTION,
        "calibration_to_holdout_ratio": (
            HOLDOUT_FRACTION / CALIBRATION_FRACTION
        ),
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
            for name, coefficient in ranked[:15]
        ],
    }


def _walk_forward_report(
    episodes: Sequence[HoldBreakEpisode],
) -> dict[str, Any]:
    output: dict[str, list[dict[str, Any]]] = {"LONG": [], "SHORT": []}
    for fold_index, (train, validation) in enumerate(
        _walk_forward_splits(episodes),
        start=1,
    ):
        for direction in ("LONG", "SHORT"):
            directional_train = tuple(
                row for row in train if row.direction == direction
            )
            directional_validation = tuple(
                row for row in validation if row.direction == direction
            )
            if (
                len(directional_train) < MIN_TRAIN_PER_DIRECTION
                or len(directional_validation) < 20
            ):
                output[direction].append(
                    {
                        "fold": fold_index,
                        "status": "INSUFFICIENT_DIRECTION_SAMPLE",
                        "train": len(directional_train),
                        "validation": len(directional_validation),
                    }
                )
                continue
            model = fit_logistic_model(directional_train)
            scored = score_episodes(
                directional_validation,
                model=model,
            )
            base_rate = float(
                np.mean(
                    [
                        row.episode.outcome.label_hold
                        for row in scored
                    ]
                )
            )
            median_threshold = float(
                np.median([row.probability_hold for row in scored])
            )
            median_metrics = _threshold_metrics(
                scored,
                threshold=median_threshold,
            )
            output[direction].append(
                {
                    "fold": fold_index,
                    "status": "EVALUATED",
                    "train": len(directional_train),
                    "validation": len(directional_validation),
                    "base_hold_rate": base_rate,
                    "brier": _brier(scored),
                    "median_probability_threshold": median_threshold,
                    "above_median": median_metrics,
                }
            )
    return output


def evaluate_hold_break_research(bars: Sequence[Bar]) -> dict[str, Any]:
    episodes = build_hold_break_episodes(bars)
    train, calibration, holdout = _split_chronological(episodes)
    base = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "label_contract": {
            "population": "UNIQUE_H1_ORIGIN_FIRST_TOUCH_WITHIN_48H",
            "decision_time": "COMPLETED_M15_BAR_IMMEDIATELY_BEFORE_FIRST_TOUCH",
            "hold": "0.50_ATR_FAVORABLE_EXCURSION_WITHIN_16_M15_BEFORE_INVALIDATION",
            "break": "M15_CLOSE_BEYOND_ZONE_BEFORE_HOLD; BREAK_WINS_SAME_BAR",
            "stall": "NEITHER_HOLD_NOR_BREAK_WITHIN_16_M15",
            "primary_binary_target": "HOLD_VS_BREAK_OR_STALL",
            "future_touch_bar_features_used": False,
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
        "walk_forward": _walk_forward_report(episodes),
    }

    if min(len(train), len(calibration), len(holdout)) <= 0:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT",
        }

    direction_results: dict[str, Any] = {}
    claim_directions = []
    for direction in ("LONG", "SHORT"):
        directional_train = tuple(
            row for row in train if row.direction == direction
        )
        directional_calibration = tuple(
            row for row in calibration if row.direction == direction
        )
        directional_holdout = tuple(
            row for row in holdout if row.direction == direction
        )

        if (
            len(directional_train) < MIN_TRAIN_PER_DIRECTION
            or len(directional_calibration)
            < MIN_CALIBRATION_SELECTED_PER_DIRECTION
            or len(directional_holdout) < MIN_CLAIM_PER_DIRECTION
        ):
            direction_results[direction] = {
                "decision": "INSUFFICIENT_DIRECTION_SAMPLE",
                "population": {
                    "train": len(directional_train),
                    "calibration": len(directional_calibration),
                    "holdout": len(directional_holdout),
                },
                "status_counts": {
                    "train": _status_counts(directional_train),
                    "calibration": _status_counts(directional_calibration),
                    "holdout": _status_counts(directional_holdout),
                },
            }
            claim_directions.append(False)
            continue

        model = fit_logistic_model(directional_train)
        calibration_scored = score_episodes(
            directional_calibration,
            model=model,
        )
        threshold, calibration_report = _calibrate_threshold(
            calibration_scored
        )
        holdout_scored = score_episodes(
            directional_holdout,
            model=model,
        )

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

        direction_results[direction] = {
            "decision": (
                "DIRECTION_GATE_MET"
                if passed
                else "DIRECTION_GATE_NOT_MET"
            ),
            "population": {
                "train": len(directional_train),
                "calibration": len(directional_calibration),
                "holdout": len(directional_holdout),
            },
            "status_counts": {
                "train": _status_counts(directional_train),
                "calibration": _status_counts(directional_calibration),
                "holdout": _status_counts(directional_holdout),
            },
            "model": _model_payload(model),
            "calibration_brier": _brier(calibration_scored),
            "calibration_threshold": calibration_report,
            "holdout_brier": _brier(holdout_scored),
            "untouched_holdout": holdout_report,
            "claim_gate_passed": passed,
        }
        claim_directions.append(passed)

    claim_passed = all(claim_directions) and len(claim_directions) == 2
    return base | {
        "models": {
            "LONG": "SEPARATE_DIRECTION_LOGISTIC_WITH_ENGINEERED_NONLINEAR_INTERACTIONS",
            "SHORT": "SEPARATE_DIRECTION_LOGISTIC_WITH_ENGINEERED_NONLINEAR_INTERACTIONS",
        },
        "features": list(FEATURE_NAMES),
        "directions": direction_results,
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
            "V177 is conditional on H1 origin zones and complements V175 destination-zone ranking.",
            "All predictive features stop at the completed M15 bar immediately before first zone touch.",
            "LONG and SHORT are modeled independently.",
            "Three expanding walk-forward folds are diagnostic; they stop before the final holdout window.",
            "The final 30% holdout is untouched by model fitting and threshold calibration.",
            "V177 cannot alter AFIC admission, position sizing, risk controls, or broker execution.",
        ],
    }

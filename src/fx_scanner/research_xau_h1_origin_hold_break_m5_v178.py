from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import cos, isfinite, pi, sin
from typing import Any, Sequence

import numpy as np

from .demo_xau_afic_path_shadow_observer import (
    OriginZone,
    _atr,
    _origin_zones,
    _resample_completed,
    _stable_zone_id,
)
from .models import Bar, ensure_utc
from .research_xau_h1_origin_hold_break_v177 import (
    _frame_times,
    _frame_trend_context,
)
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178"
ARTIFACT_CONTRACT = "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "XAUUSD"
MAX_ZONE_AGE_HOURS = 48
HOLD_REACTION_ATR = 0.50
HOLD_HORIZON_M5 = 48
PRE_TOUCH_M5_BARS = 144
PURGE_HOURS = 48

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

FEATURE_NAMES = (
    "zone_width_atr",
    "zone_age_hours_norm",
    "origin_age_hours_norm",
    "displacement_range_atr",
    "displacement_body_fraction",
    "distance_pre_touch_atr",
    "m5_efficiency_12",
    "m5_efficiency_36",
    "m5_net_atr_12",
    "m5_net_atr_36",
    "m5_body_pressure_atr_12",
    "m5_body_pressure_atr_36",
    "m5_toward_fraction_12",
    "m5_toward_fraction_36",
    "m5_approach_speed_atr_3",
    "m5_approach_speed_atr_6",
    "m5_approach_speed_atr_12",
    "m5_range3_to12",
    "m5_range12_to36",
    "m5_range36_to144",
    "m5_body3_to12",
    "m5_tick_last_to12",
    "m5_tick3_to12",
    "m5_tick12_to36",
    "m5_tick12_to144",
    "m5_tick_acceleration_3v12",
    "m5_upper_wick_pressure_12",
    "m5_lower_wick_pressure_12",
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
    "speed12_x_distance",
    "tick_accel_x_body_pressure",
    "h4_x_d1_alignment",
    "volatility_x_pressure",
)


@dataclass(frozen=True, slots=True)
class Outcome:
    status: str
    label_hold: bool
    touch_at: datetime
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
    outcome: Outcome


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


def _validate_bars(
    bars: Sequence[Bar],
    *,
    timeframe: str,
) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    normalized = str(timeframe).upper()
    if not rows:
        raise ValueError(f"V178_{normalized}_BARS_EMPTY")
    if any(
        row.symbol.upper() != SYMBOL or row.timeframe.upper() != normalized
        for row in rows
    ):
        raise ValueError(f"V178_REQUIRES_XAUUSD_{normalized}")
    if any(
        ensure_utc(rows[index].timestamp)
        >= ensure_utc(rows[index + 1].timestamp)
        for index in range(len(rows) - 1)
    ):
        raise ValueError(f"V178_{normalized}_BARS_NOT_CHRONOLOGICAL")
    return rows


def _touch(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(
    row: Bar,
    *,
    low: float,
    high: float,
    direction: str,
) -> bool:
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


def evaluate_outcome(
    bars: Sequence[Bar],
    *,
    touch_index: int,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
    horizon_m5: int = HOLD_HORIZON_M5,
    reaction_atr: float = HOLD_REACTION_ATR,
) -> Outcome:
    rows = tuple(bars)
    direction = str(direction).upper()
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)

    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if not (0 <= touch_index < len(rows)):
        raise ValueError("touch_index out of range")
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("zone bounds invalid")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_points invalid")

    touch_at = ensure_utc(rows[touch_index].timestamp)
    touch_row = rows[touch_index]
    if _invalidated(
        touch_row,
        low=low,
        high=high,
        direction=direction,
    ):
        return Outcome(
            status="BREAK_TOUCH_BAR",
            label_hold=False,
            touch_at=touch_at,
            outcome_at=touch_at,
            bars_to_outcome=0,
            max_favorable_excursion_atr=0.0,
        )

    future = rows[touch_index + 1 : touch_index + 1 + int(horizon_m5)]
    max_excursion = 0.0
    for offset, row in enumerate(future, start=1):
        max_excursion = max(
            max_excursion,
            _favorable_excursion(
                row,
                low=low,
                high=high,
                direction=direction,
            ),
        )
        # Fail closed: invalidation wins if target and invalidation occur
        # in the same M5 bar.
        if _invalidated(
            row,
            low=low,
            high=high,
            direction=direction,
        ):
            return Outcome(
                status="BREAK",
                label_hold=False,
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )
        if max_excursion + 1e-12 >= float(reaction_atr) * atr:
            return Outcome(
                status="HOLD",
                label_hold=True,
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                bars_to_outcome=offset,
                max_favorable_excursion_atr=max_excursion / atr,
            )

    if len(future) < int(horizon_m5):
        return Outcome(
            status="PENDING",
            label_hold=False,
            touch_at=touch_at,
            outcome_at=None,
            bars_to_outcome=None,
            max_favorable_excursion_atr=max_excursion / atr,
        )

    return Outcome(
        status="STALL",
        label_hold=False,
        touch_at=touch_at,
        outcome_at=ensure_utc(future[-1].timestamp),
        bars_to_outcome=int(horizon_m5),
        max_favorable_excursion_atr=max_excursion / atr,
    )


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


def _path_efficiency(
    rows: Sequence[Bar],
    *,
    direction: str,
) -> tuple[float, float]:
    closes = [float(row.close) for row in rows]
    if len(closes) < 2:
        return 0.0, 0.0
    total_path = sum(
        abs(right - left)
        for left, right in zip(closes, closes[1:])
    )
    toward_sign = 1.0 if direction == "SHORT" else -1.0
    net = toward_sign * (closes[-1] - closes[0])
    efficiency = 0.0 if total_path <= 0 else net / total_path
    return float(np.clip(efficiency, -1.0, 1.0)), float(net)


def _body_pressure(
    rows: Sequence[Bar],
    *,
    direction: str,
) -> float:
    toward_sign = 1.0 if direction == "SHORT" else -1.0
    return float(
        sum(
            toward_sign * (float(row.close) - float(row.open))
            for row in rows
        )
    )


def _toward_fraction(
    rows: Sequence[Bar],
    *,
    direction: str,
) -> float:
    toward_sign = 1.0 if direction == "SHORT" else -1.0
    return float(
        np.mean(
            [
                toward_sign * (float(row.close) - float(row.open)) > 0
                for row in rows
            ]
        )
    )


def _wick_pressure(rows: Sequence[Bar]) -> tuple[float, float]:
    upper: list[float] = []
    lower: list[float] = []
    for row in rows:
        high = float(row.high)
        low = float(row.low)
        open_ = float(row.open)
        close = float(row.close)
        rng = max(high - low, 1e-12)
        upper.append(max(0.0, high - max(open_, close)) / rng)
        lower.append(max(0.0, min(open_, close) - low) / rng)
    return float(np.mean(upper)), float(np.mean(lower))


def _session_features(
    timestamp: datetime,
) -> tuple[float, float, float, float]:
    hour = ensure_utc(timestamp).hour
    asia = float(0 <= hour < 8)
    london = float(8 <= hour < 13)
    new_york = float(13 <= hour < 21)
    other = float(not (asia or london or new_york))
    return asia, london, new_york, other


def _feature_vector(
    *,
    zone: OriginZone,
    prior_m5: Sequence[Bar],
    decision_at: datetime,
    h4,
    h4_times: Sequence[datetime],
    daily,
    daily_times: Sequence[datetime],
) -> tuple[float, ...]:
    if len(prior_m5) < PRE_TOUCH_M5_BARS:
        raise ValueError("V178_PRE_TOUCH_M5_HISTORY_INSUFFICIENT")

    atr = float(zone.h1_atr)
    if not isfinite(atr) or atr <= 0:
        raise ValueError("V178_ZONE_ATR_INVALID")

    direction = str(zone.direction).upper()
    low = float(zone.low)
    high = float(zone.high)
    last = prior_m5[-1]

    r3 = prior_m5[-3:]
    r6 = prior_m5[-6:]
    r12 = prior_m5[-12:]
    r36 = prior_m5[-36:]
    r144 = prior_m5[-144:]

    eff12, net12 = _path_efficiency(r12, direction=direction)
    eff36, net36 = _path_efficiency(r36, direction=direction)
    pressure12 = _body_pressure(r12, direction=direction)
    pressure36 = _body_pressure(r36, direction=direction)
    toward12 = _toward_fraction(r12, direction=direction)
    toward36 = _toward_fraction(r36, direction=direction)

    distance_now = _distance_to_zone(
        float(last.close),
        low=low,
        high=high,
        direction=direction,
    )

    def speed(window: Sequence[Bar]) -> float:
        first_distance = _distance_to_zone(
            float(window[0].close),
            low=low,
            high=high,
            direction=direction,
        )
        return (first_distance - distance_now) / atr

    ranges3 = np.asarray(
        [float(row.high) - float(row.low) for row in r3],
        dtype=float,
    )
    ranges12 = np.asarray(
        [float(row.high) - float(row.low) for row in r12],
        dtype=float,
    )
    ranges36 = np.asarray(
        [float(row.high) - float(row.low) for row in r36],
        dtype=float,
    )
    ranges144 = np.asarray(
        [float(row.high) - float(row.low) for row in r144],
        dtype=float,
    )

    bodies3 = np.asarray(
        [abs(float(row.close) - float(row.open)) for row in r3],
        dtype=float,
    )
    bodies12 = np.asarray(
        [abs(float(row.close) - float(row.open)) for row in r12],
        dtype=float,
    )

    ticks3 = np.asarray([float(row.tick_count) for row in r3], dtype=float)
    ticks12 = np.asarray([float(row.tick_count) for row in r12], dtype=float)
    ticks36 = np.asarray([float(row.tick_count) for row in r36], dtype=float)
    ticks144 = np.asarray([float(row.tick_count) for row in r144], dtype=float)
    tick_mean12 = float(np.mean(ticks12))

    upper_wick, lower_wick = _wick_pressure(r12)

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

    zone_age_hours = max(
        0.0,
        (
            ensure_utc(decision_at) - ensure_utc(zone.available_at)
        ).total_seconds()
        / 3600.0,
    )
    origin_age_hours = max(
        0.0,
        (
            ensure_utc(decision_at) - ensure_utc(zone.origin_at)
        ).total_seconds()
        / 3600.0,
    )
    zone_age_norm = min(1.0, zone_age_hours / MAX_ZONE_AGE_HOURS)
    origin_age_norm = min(2.0, origin_age_hours / MAX_ZONE_AGE_HOURS)

    hour_value = decision_at.hour + decision_at.minute / 60.0
    angle = 2.0 * pi * hour_value / 24.0
    asia, london, new_york, other = _session_features(decision_at)

    displacement_range = float(zone.displacement_range_atr)
    displacement_body = float(zone.displacement_body_fraction)
    distance_atr = distance_now / atr
    tick_acceleration = _safe_ratio(
        float(np.mean(ticks3) - np.mean(ticks12[:3])),
        tick_mean12,
        default=0.0,
    )

    values = [
        (high - low) / atr,
        zone_age_norm,
        origin_age_norm,
        displacement_range,
        displacement_body,
        distance_atr,
        eff12,
        eff36,
        float(np.clip(net12 / atr, -6.0, 6.0)),
        float(np.clip(net36 / atr, -10.0, 10.0)),
        float(np.clip(pressure12 / atr, -6.0, 6.0)),
        float(np.clip(pressure36 / atr, -10.0, 10.0)),
        toward12,
        toward36,
        float(np.clip(speed(r3), -6.0, 6.0)),
        float(np.clip(speed(r6), -6.0, 6.0)),
        float(np.clip(speed(r12), -8.0, 8.0)),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(ranges3)),
                    float(np.mean(ranges12)),
                    default=1.0,
                ),
                0.0,
                6.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(ranges12)),
                    float(np.mean(ranges36)),
                    default=1.0,
                ),
                0.0,
                6.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(ranges36)),
                    float(np.mean(ranges144)),
                    default=1.0,
                ),
                0.0,
                6.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(bodies3)),
                    float(np.mean(bodies12)),
                    default=1.0,
                ),
                0.0,
                6.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(float(last.tick_count), tick_mean12, default=1.0),
                0.0,
                8.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(ticks3)),
                    tick_mean12,
                    default=1.0,
                ),
                0.0,
                8.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    tick_mean12,
                    float(np.mean(ticks36)),
                    default=1.0,
                ),
                0.0,
                8.0,
            )
        ),
        float(
            np.clip(
                _safe_ratio(
                    tick_mean12,
                    float(np.mean(ticks144)),
                    default=1.0,
                ),
                0.0,
                8.0,
            )
        ),
        float(np.clip(tick_acceleration, -5.0, 5.0)),
        upper_wick,
        lower_wick,
        h4_trend,
        h4_ema,
        h4_vol,
        d1_trend,
        d1_ema,
        d1_vol,
        sin(angle),
        cos(angle),
        asia,
        london,
        new_york,
        other,
        zone_age_norm * displacement_range,
        float(np.clip(speed(r12) * distance_atr, -16.0, 16.0)),
        float(
            np.clip(
                tick_acceleration * (pressure12 / atr),
                -16.0,
                16.0,
            )
        ),
        float(np.clip(h4_trend * d1_trend, -16.0, 16.0)),
        float(
            np.clip(
                _safe_ratio(
                    float(np.mean(ranges12)),
                    float(np.mean(ranges144)),
                    default=1.0,
                )
                * (pressure12 / atr),
                -16.0,
                16.0,
            )
        ),
    ]
    if len(values) != len(FEATURE_NAMES):
        raise ValueError(
            f"V178_FEATURE_CONTRACT:{len(values)}!={len(FEATURE_NAMES)}"
        )
    bad = [
        FEATURE_NAMES[index]
        for index, value in enumerate(values)
        if not isfinite(float(value))
    ]
    if bad:
        raise ValueError("V178_NONFINITE_FEATURES:" + ",".join(bad))
    return tuple(float(value) for value in values)


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
        end_index = bisect_right(
            m5_times,
            available_at + timedelta(hours=MAX_ZONE_AGE_HOURS),
        )
        end_index = min(end_index, len(m5))
        if start_index >= end_index:
            continue

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
            or touch_index + HOLD_HORIZON_M5 >= len(m5)
        ):
            continue

        decision_index = touch_index - 1
        prior = m5[
            decision_index - PRE_TOUCH_M5_BARS + 1 : decision_index + 1
        ]
        if len(prior) < PRE_TOUCH_M5_BARS:
            continue
        decision_at = ensure_utc(m5[decision_index].timestamp) + timedelta(
            minutes=5
        )

        outcome = evaluate_outcome(
            m5,
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
            prior_m5=prior,
            decision_at=decision_at,
            h4=h4,
            h4_times=h4_times,
            daily=daily,
            daily_times=daily_times,
        )
        output.append(
            Episode(
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

    output.sort(key=lambda row: (row.touch_at, row.zone_id))
    return tuple(output)


def fit_logistic_model(
    episodes: Sequence[Episode],
) -> LogisticModel:
    if len(episodes) < MIN_TRAIN_PER_DIRECTION:
        raise ValueError(f"V178_TRAIN_SAMPLE_INSUFFICIENT:{len(episodes)}")
    matrix = np.asarray([episode.features for episode in episodes], dtype=float)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(FEATURE_NAMES)
        or not np.isfinite(matrix).all()
    ):
        raise ValueError("V178_FEATURE_MATRIX_INVALID")

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
    value = float(
        np.clip(
            normalized @ coefficients + model.intercept,
            -30.0,
            30.0,
        )
    )
    return float(1.0 / (1.0 + np.exp(-value)))


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
    holdout = tuple(
        row for row in rows if row.touch_at >= holdout_start
    )
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


def _model_payload(
    model: LogisticModel,
) -> dict[str, Any]:
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
                    "median_probability_threshold": median_threshold,
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
            "population": "UNIQUE_H1_ORIGIN_FIRST_M5_TOUCH_WITHIN_48H",
            "decision_time": "COMPLETED_M5_BAR_IMMEDIATELY_BEFORE_FIRST_M5_TOUCH",
            "hold": "0.50_ATR_FAVORABLE_EXCURSION_WITHIN_48_M5_BEFORE_INVALIDATION",
            "break": "M5_CLOSE_BEYOND_ZONE_BEFORE_HOLD; BREAK_WINS_SAME_BAR",
            "stall": "NEITHER_HOLD_NOR_BREAK_WITHIN_48_M5",
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
        "features": list(FEATURE_NAMES),
        "walk_forward": _walk_forward_report(episodes),
    }

    if min(len(train), len(calibration), len(holdout)) <= 0:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT",
        }

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
                "status_counts": {
                    "train": _status_counts(d_train),
                    "calibration": _status_counts(d_calibration),
                    "holdout": _status_counts(d_holdout),
                },
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
        holdout_scored = score_episodes(
            d_holdout,
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
            "V178 moves the hold-vs-break decision from the final pre-touch M15 close to the final pre-touch M5 close.",
            "H1 origin construction remains based on the existing causal structural contract.",
            "Historical spread is excluded because the current adapter does not provide historical bid/ask series.",
            "No V178 output has AFIC admission, sizing, risk, or broker execution authority.",
        ],
    }

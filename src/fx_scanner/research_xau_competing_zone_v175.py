from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
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

RESEARCH_VERSION = "XAU_COMPETING_ZONE_RANKER_V175"
ARTIFACT_CONTRACT = "XAU_COMPETING_ZONE_RANKER_V175_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

TOUCH_HORIZON_M15 = 64
MAX_REACTION_HORIZON_M15 = 32
PRIMARY_REACTION_ATR = 0.50
PRIMARY_REACTION_HORIZON_M15 = 16
REACTION_ATR_LEVELS = (0.25, 0.50, 0.75)
REACTION_HORIZONS_M15 = (8, 16, 32)
SPLIT_PURGE_HOURS = 24
CLAIM_PRECISION = 0.80
MIN_CLAIM_PER_DIRECTION = 100
MIN_CALIBRATION_PER_DIRECTION = 30
MIN_DIRECTION_COVERAGE = 0.05
ROUND_STEP_USD = 10.0
MAX_CANDIDATES_PER_DIRECTION = 12
LOGISTIC_ITERATIONS = 800
LOGISTIC_LEARNING_RATE = 0.05
LOGISTIC_L2 = 0.10

SOURCE_NAMES = (
    "H1_ORIGIN",
    "PREVIOUS_DAY",
    "PREVIOUS_WEEK",
    "SESSION_ASIA",
    "SESSION_LONDON",
    "SESSION_NEW_YORK",
    "ROUND_NUMBER",
)

SESSION_WINDOWS = {
    "SESSION_ASIA": (0, 8),
    "SESSION_LONDON": (8, 13),
    "SESSION_NEW_YORK": (13, 21),
}

FEATURE_NAMES = (
    "distance_atr",
    "width_atr",
    "age_days",
    "round_distance_atr",
    "prior_touches",
    "displacement_range_atr",
    "displacement_body_fraction",
    "approach_efficiency",
    "approach_range_atr",
    "h4_directional_close_location",
    "h4_trend_alignment",
    "volatility_ratio",
    "distance_rank",
    "candidate_count",
    "confluence_count",
    "structural_role",
    "hour_sin",
    "hour_cos",
) + tuple(f"source_{name.lower()}" for name in SOURCE_NAMES)


@dataclass(frozen=True, slots=True)
class CandidateZone:
    source: str
    source_id: str
    direction: str
    low: float
    high: float
    available_at: datetime
    displacement_range_atr: float
    displacement_body_fraction: float
    prior_touches: int
    structural_role: float


@dataclass(frozen=True, slots=True)
class MultiPathOutcome:
    status: str
    touched: bool
    touch_at: datetime | None
    invalidated_at: datetime | None
    bars_to_touch: int | None
    reactions: dict[str, bool]
    primary_success: bool


@dataclass(frozen=True, slots=True)
class CandidateEpisode:
    map_at: datetime
    candidate_id: str
    source: str
    direction: str
    zone_low: float
    zone_high: float
    map_price: float
    features: tuple[float, ...]
    outcome: MultiPathOutcome


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
    episode: CandidateEpisode
    touch_probability: float
    reaction_probability: float
    path_probability: float


def _reaction_key(atr_multiple: float, horizon: int) -> str:
    return f"atr{int(round(atr_multiple * 100)):03d}_h{int(horizon)}"


PRIMARY_REACTION_KEY = _reaction_key(
    PRIMARY_REACTION_ATR, PRIMARY_REACTION_HORIZON_M15
)


def _touch(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(row: Bar, *, low: float, high: float, direction: str) -> bool:
    return (
        float(row.close) > high
        if direction == "SHORT"
        else float(row.close) < low
    )


def evaluate_multi_zone_path(
    bars: Sequence[Bar],
    *,
    forecast_at: datetime,
    direction: str,
    zone_low: float,
    zone_high: float,
    atr_points: float,
) -> MultiPathOutcome:
    normalized = str(direction).upper().strip()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    low = float(zone_low)
    high = float(zone_high)
    atr = float(atr_points)
    if not (isfinite(low) and isfinite(high) and low < high):
        raise ValueError("zone bounds must be finite and ordered")
    if not isfinite(atr) or atr <= 0:
        raise ValueError("atr_points must be positive and finite")

    start = ensure_utc(forecast_at)
    rows = tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) >= start
    )
    reaction_keys = {
        _reaction_key(level, horizon): False
        for level in REACTION_ATR_LEVELS
        for horizon in REACTION_HORIZONS_M15
    }
    touch_index: int | None = None
    touch_at: datetime | None = None

    for index, row in enumerate(rows[:TOUCH_HORIZON_M15]):
        touched = _touch(row, low=low, high=high)
        invalid = _invalidated(
            row, low=low, high=high, direction=normalized
        )
        if invalid:
            stamp = ensure_utc(row.timestamp)
            return MultiPathOutcome(
                status=(
                    "TOUCH_INVALIDATED_SAME_BAR"
                    if touched
                    else "INVALIDATED_BEFORE_TOUCH"
                ),
                touched=touched,
                touch_at=stamp if touched else None,
                invalidated_at=stamp,
                bars_to_touch=index if touched else None,
                reactions=reaction_keys,
                primary_success=False,
            )
        if touched:
            touch_index = index
            touch_at = ensure_utc(row.timestamp)
            break

    if touch_index is None:
        return MultiPathOutcome(
            status=(
                "TOUCH_TIMEOUT"
                if len(rows) >= TOUCH_HORIZON_M15
                else "PENDING_TOUCH"
            ),
            touched=False,
            touch_at=None,
            invalidated_at=None,
            bars_to_touch=None,
            reactions=reaction_keys,
            primary_success=False,
        )

    max_excursion = 0.0
    invalidated_at: datetime | None = None
    reaction_rows = rows[
        touch_index + 1 : touch_index + 1 + MAX_REACTION_HORIZON_M15
    ]
    for offset, row in enumerate(reaction_rows, start=1):
        invalid = _invalidated(
            row, low=low, high=high, direction=normalized
        )
        excursion = (
            max(0.0, float(row.high) - high)
            if normalized == "LONG"
            else max(0.0, low - float(row.low))
        )
        max_excursion = max(max_excursion, excursion)
        # Invalidation wins when both extremes occur in the same OHLC bar.
        if invalid:
            invalidated_at = ensure_utc(row.timestamp)
            break
        for level in REACTION_ATR_LEVELS:
            if max_excursion + 1e-12 < level * atr:
                continue
            for horizon in REACTION_HORIZONS_M15:
                if offset <= horizon:
                    reaction_keys[_reaction_key(level, horizon)] = True

    primary = bool(reaction_keys[PRIMARY_REACTION_KEY])
    if invalidated_at is not None and not primary:
        status = "INVALIDATED_AFTER_TOUCH"
    elif primary:
        status = "TOUCH_REVERSED"
    elif len(reaction_rows) >= MAX_REACTION_HORIZON_M15:
        status = "REACTION_TIMEOUT"
    else:
        status = "PENDING_REACTION"
    return MultiPathOutcome(
        status=status,
        touched=True,
        touch_at=touch_at,
        invalidated_at=invalidated_at,
        bars_to_touch=touch_index,
        reactions=reaction_keys,
        primary_success=primary,
    )


def _level_zone(
    *,
    source: str,
    source_id: str,
    level: float,
    natural_role: str,
    available_at: datetime,
    map_price: float,
    atr_points: float,
) -> CandidateZone | None:
    half_width = max(0.05 * atr_points, min(0.12 * atr_points, 2.0))
    low = float(level) - half_width
    high = float(level) + half_width
    if low > map_price:
        direction = "SHORT"
    elif high < map_price:
        direction = "LONG"
    else:
        return None
    structural_role = float(
        (natural_role == "HIGH" and direction == "SHORT")
        or (natural_role == "LOW" and direction == "LONG")
    )
    return CandidateZone(
        source=source,
        source_id=source_id,
        direction=direction,
        low=low,
        high=high,
        available_at=ensure_utc(available_at),
        displacement_range_atr=0.0,
        displacement_body_fraction=0.0,
        prior_touches=0,
        structural_role=structural_role,
    )


def _session_levels(rows: Sequence[Bar]) -> tuple[dict[str, Any], ...]:
    grouped: dict[tuple[datetime, str], list[Bar]] = defaultdict(list)
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        day = datetime.combine(stamp.date(), time.min, tzinfo=UTC)
        for name, (start_hour, end_hour) in SESSION_WINDOWS.items():
            if start_hour <= stamp.hour < end_hour:
                grouped[(day, name)].append(row)
                break
    out: list[dict[str, Any]] = []
    for (day, name), values in grouped.items():
        start_hour, end_hour = SESSION_WINDOWS[name]
        available_at = day + timedelta(hours=end_hour)
        if len(values) < max(4, (end_hour - start_hour) * 2):
            continue
        out.append(
            {
                "source": name,
                "available_at": available_at,
                "source_id": f"{name}:{day.date().isoformat()}",
                "high": max(float(row.high) for row in values),
                "low": min(float(row.low) for row in values),
            }
        )
    return tuple(sorted(out, key=lambda item: item["available_at"]))


def _invalidated_at(zone: OriginZone, rows: Sequence[Bar]) -> datetime | None:
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        if stamp < ensure_utc(zone.available_at):
            continue
        if _invalidated(
            row,
            low=float(zone.low),
            high=float(zone.high),
            direction=zone.direction,
        ):
            return stamp
    return None


def _prior_touch_count(
    zone: OriginZone, rows: Sequence[Bar], *, map_at: datetime
) -> int:
    start = ensure_utc(zone.available_at)
    end = ensure_utc(map_at)
    return sum(
        _touch(row, low=float(zone.low), high=float(zone.high))
        for row in rows
        if start <= ensure_utc(row.timestamp) < end
    )


def _frame_times(frame: pd.DataFrame) -> tuple[datetime, ...]:
    return tuple(ensure_utc(value.to_pydatetime()) for value in frame["time"])


def _last_frame_row(
    frame: pd.DataFrame,
    timestamp: datetime,
    *,
    times: Sequence[datetime] | None = None,
):
    if frame.empty:
        return None
    frame_times = tuple(times) if times is not None else _frame_times(frame)
    index = bisect_right(frame_times, ensure_utc(timestamp)) - 1
    return None if index < 0 else frame.iloc[index]


def _map_context(
    *,
    h4: pd.DataFrame,
    h4_index: int,
    prior_bars: Sequence[Bar],
    direction: str,
    atr_points: float,
) -> dict[str, float]:
    row = h4.iloc[h4_index]
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    candle_range = max(high - low, 1e-12)
    close_location = (close - low) / candle_range
    directional_location = (
        close_location if direction == "LONG" else 1.0 - close_location
    )

    closes = [float(bar.close) for bar in prior_bars[-8:]]
    total_path = sum(
        abs(right - left) for left, right in zip(closes, closes[1:])
    )
    directional_net = (
        closes[-1] - closes[0]
        if direction == "SHORT"
        else closes[0] - closes[-1]
    ) if len(closes) >= 2 else 0.0
    approach_efficiency = (
        0.0 if total_path <= 0 else max(0.0, directional_net) / total_path
    )
    approach_range = (
        0.0
        if not prior_bars
        else (
            max(float(bar.high) for bar in prior_bars[-8:])
            - min(float(bar.low) for bar in prior_bars[-8:])
        )
        / atr_points
    )

    ema20 = float(row.get("ema20", close))
    trend_alignment = (
        (close - ema20) / atr_points
        if direction == "LONG"
        else (ema20 - close) / atr_points
    )
    short_atr = float(row.get("atr5", atr_points))
    long_atr = float(row.get("atr20", atr_points))
    volatility_ratio = short_atr / max(long_atr, 1e-12)
    return {
        "approach_efficiency": float(approach_efficiency),
        "approach_range_atr": float(approach_range),
        "h4_directional_close_location": float(directional_location),
        "h4_trend_alignment": float(np.clip(trend_alignment, -4.0, 4.0)),
        "volatility_ratio": float(np.clip(volatility_ratio, 0.0, 4.0)),
    }


def _feature_vector(
    *,
    candidate: CandidateZone,
    map_at: datetime,
    map_price: float,
    atr_points: float,
    context: dict[str, float],
    distance_rank: int,
    candidate_count: int,
    confluence_count: int,
) -> tuple[float, ...]:
    distance = (
        candidate.low - map_price
        if candidate.direction == "SHORT"
        else map_price - candidate.high
    )
    boundary = candidate.low if candidate.direction == "SHORT" else candidate.high
    round_distance = abs(
        boundary - round(boundary / ROUND_STEP_USD) * ROUND_STEP_USD
    )
    hour_angle = 2.0 * pi * (map_at.hour + map_at.minute / 60.0) / 24.0
    values = [
        max(0.0, distance) / atr_points,
        (candidate.high - candidate.low) / atr_points,
        min(7.0, max(0.0, (map_at - candidate.available_at).total_seconds() / 86400.0)),
        round_distance / atr_points,
        float(min(candidate.prior_touches, 5)),
        float(candidate.displacement_range_atr),
        float(candidate.displacement_body_fraction),
        context["approach_efficiency"],
        context["approach_range_atr"],
        context["h4_directional_close_location"],
        context["h4_trend_alignment"],
        context["volatility_ratio"],
        float(distance_rank),
        float(candidate_count),
        float(confluence_count),
        float(candidate.structural_role),
        sin(hour_angle),
        cos(hour_angle),
    ]
    values.extend(float(candidate.source == name) for name in SOURCE_NAMES)
    return tuple(float(value) for value in values)


def _round_candidates(
    *, map_at: datetime, map_price: float, atr_points: float
) -> tuple[CandidateZone, ...]:
    base = round(map_price / ROUND_STEP_USD) * ROUND_STEP_USD
    levels = {
        base + offset * ROUND_STEP_USD
        for offset in (-2, -1, 0, 1, 2)
    }
    out = []
    for level in sorted(levels):
        candidate = _level_zone(
            source="ROUND_NUMBER",
            source_id=f"ROUND:{map_at.isoformat()}:{level:.2f}",
            level=level,
            natural_role="ROUND",
            available_at=map_at,
            map_price=map_price,
            atr_points=atr_points,
        )
        if candidate is not None:
            out.append(candidate)
    return tuple(out)


def _level_candidates(
    *,
    frame: pd.DataFrame,
    source: str,
    map_at: datetime,
    map_price: float,
    atr_points: float,
    frame_times: Sequence[datetime] | None = None,
) -> tuple[CandidateZone, ...]:
    row = _last_frame_row(frame, map_at, times=frame_times)
    if row is None:
        return ()
    available_at = ensure_utc(row["time"].to_pydatetime())
    source_id = f"{source}:{available_at.isoformat()}"
    out = []
    for role, column in (("HIGH", "high"), ("LOW", "low")):
        candidate = _level_zone(
            source=source,
            source_id=f"{source_id}:{role}",
            level=float(row[column]),
            natural_role=role,
            available_at=available_at,
            map_price=map_price,
            atr_points=atr_points,
        )
        if candidate is not None:
            out.append(candidate)
    return tuple(out)


def build_competing_zone_episodes(
    bars: Sequence[Bar],
) -> tuple[CandidateEpisode, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 2_000:
        return ()
    row_times = tuple(ensure_utc(row.timestamp) for row in rows)
    last_closed_at = row_times[-1] + timedelta(minutes=15)
    h1 = _resample_completed(rows, "1h", as_of=last_closed_at)
    h1["atr14"] = _atr(h1, 14)
    h4 = _resample_completed(rows, "4h", as_of=last_closed_at)
    h4["ema20"] = h4["close"].ewm(span=20, adjust=False).mean()
    h4["atr5"] = _atr(h4, 5)
    h4["atr20"] = _atr(h4, 20)
    daily = _resample_completed(rows, "1D", as_of=last_closed_at)
    weekly = _resample_completed(rows, "W-MON", as_of=last_closed_at)
    h1_times = _frame_times(h1)
    daily_times = _frame_times(daily)
    weekly_times = _frame_times(weekly)
    origin_zones = _origin_zones(rows, as_of=last_closed_at)
    origin_invalidated = {
        _stable_zone_id(zone): _invalidated_at(zone, rows)
        for zone in origin_zones
    }
    session_levels = _session_levels(rows)
    session_times = tuple(item["available_at"] for item in session_levels)
    episodes: list[CandidateEpisode] = []

    for h4_index in range(20, len(h4)):
        map_row = h4.iloc[h4_index]
        map_at = ensure_utc(map_row["time"].to_pydatetime())
        map_price = float(map_row["close"])
        h1_row = _last_frame_row(h1, map_at, times=h1_times)
        if h1_row is None:
            continue
        atr_points = float(h1_row.get("atr14", np.nan))
        if not isfinite(atr_points) or atr_points <= 0:
            continue
        row_index = bisect_right(row_times, map_at - timedelta(microseconds=1))
        prior_bars = rows[max(0, row_index - 64) : row_index]
        future_bars = rows[
            row_index : row_index + TOUCH_HORIZON_M15 + MAX_REACTION_HORIZON_M15
        ]
        if len(future_bars) < TOUCH_HORIZON_M15:
            continue

        candidates: list[CandidateZone] = []
        for zone in origin_zones:
            available_at = ensure_utc(zone.available_at)
            if not (available_at <= map_at <= available_at + timedelta(hours=48)):
                continue
            invalidated = origin_invalidated[_stable_zone_id(zone)]
            if invalidated is not None and invalidated < map_at:
                continue
            if zone.direction == "SHORT" and float(zone.low) <= map_price:
                continue
            if zone.direction == "LONG" and float(zone.high) >= map_price:
                continue
            candidates.append(
                CandidateZone(
                    source="H1_ORIGIN",
                    source_id=_stable_zone_id(zone),
                    direction=zone.direction,
                    low=float(zone.low),
                    high=float(zone.high),
                    available_at=available_at,
                    displacement_range_atr=float(zone.displacement_range_atr),
                    displacement_body_fraction=float(zone.displacement_body_fraction),
                    prior_touches=_prior_touch_count(
                        zone,
                        rows[
                            bisect_right(
                                row_times,
                                available_at - timedelta(microseconds=1),
                            ) : row_index
                        ],
                        map_at=map_at,
                    ),
                    structural_role=1.0,
                )
            )

        candidates.extend(
            _level_candidates(
                frame=daily,
                source="PREVIOUS_DAY",
                map_at=map_at,
                map_price=map_price,
                atr_points=atr_points,
                frame_times=daily_times,
            )
        )
        candidates.extend(
            _level_candidates(
                frame=weekly,
                source="PREVIOUS_WEEK",
                map_at=map_at,
                map_price=map_price,
                atr_points=atr_points,
                frame_times=weekly_times,
            )
        )
        session_index = bisect_right(session_times, map_at)
        for item in session_levels[max(0, session_index - 6) : session_index]:
            if map_at - item["available_at"] > timedelta(hours=24):
                continue
            for role in ("HIGH", "LOW"):
                candidate = _level_zone(
                    source=item["source"],
                    source_id=f"{item['source_id']}:{role}",
                    level=float(item[role.lower()]),
                    natural_role=role,
                    available_at=item["available_at"],
                    map_price=map_price,
                    atr_points=atr_points,
                )
                if candidate is not None:
                    candidates.append(candidate)
        candidates.extend(
            _round_candidates(
                map_at=map_at,
                map_price=map_price,
                atr_points=atr_points,
            )
        )

        by_direction: dict[str, list[CandidateZone]] = {"LONG": [], "SHORT": []}
        for candidate in candidates:
            distance = (
                candidate.low - map_price
                if candidate.direction == "SHORT"
                else map_price - candidate.high
            )
            if 0.0 <= distance <= 2.0 * atr_points:
                by_direction[candidate.direction].append(candidate)

        for direction in ("LONG", "SHORT"):
            directional = sorted(
                by_direction[direction],
                key=lambda candidate: (
                    candidate.low - map_price
                    if direction == "SHORT"
                    else map_price - candidate.high
                ),
            )[:MAX_CANDIDATES_PER_DIRECTION]
            if not directional:
                continue
            context = _map_context(
                h4=h4,
                h4_index=h4_index,
                prior_bars=prior_bars,
                direction=direction,
                atr_points=atr_points,
            )
            boundaries = [
                candidate.low if direction == "SHORT" else candidate.high
                for candidate in directional
            ]
            for rank, candidate in enumerate(directional, start=1):
                boundary = candidate.low if direction == "SHORT" else candidate.high
                confluence = sum(
                    abs(other - boundary) <= 0.15 * atr_points
                    for other in boundaries
                )
                features = _feature_vector(
                    candidate=candidate,
                    map_at=map_at,
                    map_price=map_price,
                    atr_points=atr_points,
                    context=context,
                    distance_rank=rank,
                    candidate_count=len(directional),
                    confluence_count=confluence,
                )
                outcome = evaluate_multi_zone_path(
                    future_bars,
                    forecast_at=map_at,
                    direction=direction,
                    zone_low=candidate.low,
                    zone_high=candidate.high,
                    atr_points=atr_points,
                )
                episodes.append(
                    CandidateEpisode(
                        map_at=map_at,
                        candidate_id=(
                            f"{map_at.isoformat()}|{direction}|{candidate.source}|"
                            f"{candidate.source_id}"
                        ),
                        source=candidate.source,
                        direction=direction,
                        zone_low=candidate.low,
                        zone_high=candidate.high,
                        map_price=map_price,
                        features=features,
                        outcome=outcome,
                    )
                )
    return tuple(episodes)


def fit_logistic_model(
    episodes: Sequence[CandidateEpisode], *, target: str
) -> LogisticModel:
    if target not in {"touch", "reaction"}:
        raise ValueError("target must be touch or reaction")
    selected = [
        episode
        for episode in episodes
        if episode.outcome.status not in {"PENDING_TOUCH", "PENDING_REACTION"}
        and (target == "touch" or episode.outcome.touched)
    ]
    if len(selected) < 20:
        raise ValueError(f"insufficient {target} training rows")
    matrix = np.asarray([episode.features for episode in selected], dtype=float)
    labels = np.asarray(
        [
            float(episode.outcome.touched)
            if target == "touch"
            else float(episode.outcome.primary_success)
            for episode in selected
        ],
        dtype=float,
    )
    means = np.mean(matrix, axis=0)
    scales = np.std(matrix, axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    normalized = np.clip((matrix - means) / scales, -8.0, 8.0)
    coefficients = np.zeros(normalized.shape[1], dtype=float)
    positive_rate = float(np.mean(labels))
    intercept = float(
        np.log((positive_rate + 1e-6) / (1.0 - positive_rate + 1e-6))
    )
    for _ in range(LOGISTIC_ITERATIONS):
        logits = np.clip(normalized @ coefficients + intercept, -30.0, 30.0)
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        errors = probabilities - labels
        coefficient_gradient = (
            normalized.T @ errors / len(labels)
            + LOGISTIC_L2 * coefficients / len(labels)
        )
        intercept_gradient = float(np.mean(errors))
        coefficients -= LOGISTIC_LEARNING_RATE * coefficient_gradient
        intercept -= LOGISTIC_LEARNING_RATE * intercept_gradient
    return LogisticModel(
        feature_names=FEATURE_NAMES,
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        positive_rate=positive_rate,
        rows=len(selected),
    )


def predict_probability(model: LogisticModel, features: Sequence[float]) -> float:
    vector = np.asarray(features, dtype=float)
    means = np.asarray(model.means, dtype=float)
    scales = np.asarray(model.scales, dtype=float)
    coefficients = np.asarray(model.coefficients, dtype=float)
    normalized = np.clip((vector - means) / scales, -8.0, 8.0)
    logit = float(np.clip(normalized @ coefficients + model.intercept, -30.0, 30.0))
    return float(1.0 / (1.0 + np.exp(-logit)))


def score_episodes(
    episodes: Sequence[CandidateEpisode],
    *,
    touch_model: LogisticModel,
    reaction_model: LogisticModel,
) -> tuple[ScoredEpisode, ...]:
    out = []
    for episode in episodes:
        touch_probability = predict_probability(touch_model, episode.features)
        reaction_probability = predict_probability(reaction_model, episode.features)
        out.append(
            ScoredEpisode(
                episode=episode,
                touch_probability=touch_probability,
                reaction_probability=reaction_probability,
                path_probability=touch_probability * reaction_probability,
            )
        )
    return tuple(out)


def _top_per_map_direction(
    rows: Sequence[ScoredEpisode],
) -> tuple[ScoredEpisode, ...]:
    grouped: dict[tuple[datetime, str], list[ScoredEpisode]] = defaultdict(list)
    for row in rows:
        grouped[(row.episode.map_at, row.episode.direction)].append(row)
    return tuple(
        max(
            values,
            key=lambda row: (
                row.path_probability,
                -float(row.episode.features[0]),
            ),
        )
        for _, values in sorted(grouped.items())
    )


def _split_by_map(
    episodes: Sequence[CandidateEpisode],
) -> tuple[tuple[CandidateEpisode, ...], ...]:
    map_times = sorted({episode.map_at for episode in episodes})
    train_index = int(len(map_times) * 0.60)
    calibration_index = int(len(map_times) * 0.80)
    if not map_times or train_index >= len(map_times) or calibration_index >= len(map_times):
        return (), (), ()
    calibration_start = map_times[train_index]
    test_start = map_times[calibration_index]
    purge = timedelta(hours=SPLIT_PURGE_HOURS)
    train = tuple(
        episode
        for episode in episodes
        if episode.map_at < calibration_start - purge
    )
    calibration = tuple(
        episode
        for episode in episodes
        if calibration_start <= episode.map_at < test_start - purge
    )
    test = tuple(
        episode for episode in episodes if episode.map_at >= test_start
    )
    return train, calibration, test


def _selected_metrics(
    rows: Sequence[ScoredEpisode], *, direction: str, universe: int
) -> dict[str, Any]:
    selected = [row for row in rows if row.episode.direction == direction]
    touched = [row for row in selected if row.episode.outcome.touched]
    path_hits = sum(row.episode.outcome.primary_success for row in selected)
    reaction_hits = sum(row.episode.outcome.primary_success for row in touched)
    touch_hits = len(touched)
    return {
        "selected": len(selected),
        "universe": int(universe),
        "coverage": None if universe <= 0 else len(selected) / universe,
        "touch_precision": None if not selected else touch_hits / len(selected),
        "conditional_reaction_precision": (
            None if not touched else reaction_hits / len(touched)
        ),
        "path_precision": None if not selected else path_hits / len(selected),
        "path_wilson_lower_95": wilson_lower_bound(path_hits, len(selected)),
        "path_hits": int(path_hits),
        "source_mix": {
            source: sum(row.episode.source == source for row in selected)
            for source in SOURCE_NAMES
            if any(row.episode.source == source for row in selected)
        },
    }


def _calibrate_threshold(
    rows: Sequence[ScoredEpisode], *, direction: str
) -> tuple[float | None, dict[str, Any]]:
    directional = [row for row in rows if row.episode.direction == direction]
    if len(directional) < MIN_CALIBRATION_PER_DIRECTION:
        return None, {"reason": "INSUFFICIENT_DIRECTIONAL_CALIBRATION", "rows": len(directional)}
    probabilities = np.asarray([row.path_probability for row in directional])
    thresholds = sorted(
        {
            0.0,
            0.05,
            0.10,
            0.15,
            0.20,
            0.25,
            0.30,
            0.40,
            0.50,
            *(
                float(np.quantile(probabilities, quantile))
                for quantile in (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90)
            ),
        }
    )
    ranked = []
    for threshold in thresholds:
        chosen = [row for row in directional if row.path_probability >= threshold]
        coverage = len(chosen) / len(directional)
        if (
            len(chosen) < MIN_CALIBRATION_PER_DIRECTION
            or coverage < MIN_DIRECTION_COVERAGE
        ):
            continue
        hits = sum(row.episode.outcome.primary_success for row in chosen)
        precision = hits / len(chosen)
        lower = float(wilson_lower_bound(hits, len(chosen)) or 0.0)
        ranked.append((lower, precision, coverage, threshold, chosen))
    if not ranked:
        return None, {"reason": "NO_THRESHOLD_SURVIVED", "rows": len(directional)}
    lower, precision, coverage, threshold, chosen = max(
        ranked, key=lambda item: (item[0], item[1], item[2])
    )
    return float(threshold), {
        "threshold": float(threshold),
        "selected": len(chosen),
        "universe": len(directional),
        "coverage": float(coverage),
        "path_precision": float(precision),
        "path_wilson_lower_95": float(lower),
    }


def _label_matrix(
    rows: Sequence[ScoredEpisode], *, direction: str
) -> dict[str, Any]:
    selected = [row for row in rows if row.episode.direction == direction]
    out: dict[str, Any] = {}
    for level in REACTION_ATR_LEVELS:
        for horizon in REACTION_HORIZONS_M15:
            key = _reaction_key(level, horizon)
            hits = sum(row.episode.outcome.reactions[key] for row in selected)
            out[key] = {
                "hits": int(hits),
                "total": len(selected),
                "path_precision": None if not selected else hits / len(selected),
                "wilson_lower_95": wilson_lower_bound(hits, len(selected)),
            }
    return out


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


def evaluate_competing_zone_research(bars: Sequence[Bar]) -> dict[str, Any]:
    episodes = tuple(
        episode
        for episode in build_competing_zone_episodes(bars)
        if episode.outcome.status not in {"PENDING_TOUCH", "PENDING_REACTION"}
    )
    train, calibration, test = _split_by_map(episodes)
    if min(len(train), len(calibration), len(test)) <= 0:
        return {
            "research_version": RESEARCH_VERSION,
            "artifact_contract": ARTIFACT_CONTRACT,
            "execution_influence": False,
            "decision": "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT",
            "episodes": len(episodes),
        }

    touch_model = fit_logistic_model(train, target="touch")
    reaction_model = fit_logistic_model(train, target="reaction")
    calibration_top = _top_per_map_direction(
        score_episodes(
            calibration,
            touch_model=touch_model,
            reaction_model=reaction_model,
        )
    )
    test_top = _top_per_map_direction(
        score_episodes(
            test,
            touch_model=touch_model,
            reaction_model=reaction_model,
        )
    )

    thresholds: dict[str, float | None] = {}
    calibration_report: dict[str, Any] = {}
    selected_test: list[ScoredEpisode] = []
    test_report: dict[str, Any] = {}
    label_matrix: dict[str, Any] = {}
    claim_directions = []
    for direction in ("LONG", "SHORT"):
        threshold, report = _calibrate_threshold(
            calibration_top, direction=direction
        )
        thresholds[direction] = threshold
        calibration_report[direction] = report
        directional_universe = sum(
            row.episode.direction == direction for row in test_top
        )
        chosen = [
            row
            for row in test_top
            if row.episode.direction == direction
            and threshold is not None
            and row.path_probability >= threshold
        ]
        selected_test.extend(chosen)
        metrics = _selected_metrics(
            chosen, direction=direction, universe=directional_universe
        )
        test_report[direction] = metrics
        label_matrix[direction] = _label_matrix(chosen, direction=direction)
        claim_directions.append(
            metrics["selected"] >= MIN_CLAIM_PER_DIRECTION
            and (metrics["path_precision"] or 0.0) >= CLAIM_PRECISION
            and (metrics["path_wilson_lower_95"] or 0.0) >= CLAIM_PRECISION
        )

    claim_passed = all(claim_directions)
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "candidate_sources": list(SOURCE_NAMES),
        "primary_label": {
            "touch_horizon_m15": TOUCH_HORIZON_M15,
            "reaction_atr_multiple": PRIMARY_REACTION_ATR,
            "reaction_horizon_m15": PRIMARY_REACTION_HORIZON_M15,
            "same_bar_ambiguity": "INVALIDATION_WINS_TOUCH_BAR_REACTION_IGNORED",
        },
        "episodes": len(episodes),
        "unique_maps": len({episode.map_at for episode in episodes}),
        "split": {
            "train_candidates": len(train),
            "calibration_candidates": len(calibration),
            "test_candidates": len(test),
            "purge_hours": SPLIT_PURGE_HOURS,
        },
        "models": {
            "touch": _model_payload(touch_model),
            "conditional_reaction": _model_payload(reaction_model),
            "path_probability": "P_TOUCH_X_P_REACTION_GIVEN_TOUCH",
        },
        "calibration": calibration_report,
        "thresholds": thresholds,
        "untouched_test": test_report,
        "untouched_test_label_matrix": label_matrix,
        "claim_gate": {
            "target_path_precision": CLAIM_PRECISION,
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
            "V175 ranks competing zones separately for LONG and SHORT on each completed H4 map.",
            "The touch model and conditional-reaction model are fitted only on the training period.",
            "Thresholds are frozen on calibration and applied once to untouched test data.",
            "V175 cannot alter AFIC admission, position sizing, or broker execution.",
        ],
    }

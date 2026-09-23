from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_afic_path_shadow_observer import (
    OriginZone,
    _atr,
    _origin_zones,
    _resample_completed,
    _stable_zone_id,
    _zone_touch_lifecycle,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_HTF_STRATEGIC_REGIME_V180"
ARTIFACT_CONTRACT = "XAU_HTF_STRATEGIC_REGIME_V180_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

RAW_DIRECTION_THRESHOLD = 0.18
STRONG_SWITCH_THRESHOLD = 0.45
NEUTRALIZE_THRESHOLD = 0.08
SWITCH_CONFIRM_H4 = 2
NEUTRAL_CONFIRM_H4 = 3
CANONICAL_ZONE_MAX_AGE_HOURS = 24
SHADOW_ZONE_MAX_AGE_HOURS = 48
TEST_FRACTION = 0.20

COMPONENT_WEIGHTS = {
    "d1_close_ema20": 0.15,
    "d1_ema20_ema50": 0.12,
    "d1_ema20_slope": 0.10,
    "d1_return5": 0.08,
    "d1_structure": 0.10,
    "h4_close_ema20": 0.12,
    "h4_ema20_ema50": 0.10,
    "h4_ema20_slope": 0.08,
    "h4_return4": 0.07,
    "h4_structure": 0.08,
}


@dataclass(frozen=True, slots=True)
class RegimePoint:
    map_at: datetime
    close: float
    raw_score: float
    raw_direction: str
    strategic_bias: str
    baseline_h4_direction: str
    switch_pending_direction: str | None
    switch_pending_count: int
    neutral_pending_count: int
    components: dict[str, float]


def _frame_times(frame: pd.DataFrame) -> tuple[datetime, ...]:
    return tuple(ensure_utc(value.to_pydatetime()) for value in frame["time"])


def _last_frame_index(
    times: Sequence[datetime],
    timestamp: datetime,
) -> int | None:
    index = bisect_right(times, ensure_utc(timestamp)) - 1
    return None if index < 0 else index


def _direction_from_score(score: float) -> str:
    if score >= RAW_DIRECTION_THRESHOLD:
        return "LONG"
    if score <= -RAW_DIRECTION_THRESHOLD:
        return "SHORT"
    return "NEUTRAL"


def _structure_component(
    frame: pd.DataFrame,
    index: int,
    *,
    recent: int = 3,
) -> float:
    if index < recent * 2 - 1:
        return 0.0
    current = frame.iloc[index - recent + 1 : index + 1]
    previous = frame.iloc[index - recent * 2 + 1 : index - recent + 1]
    current_high = float(current["high"].max())
    current_low = float(current["low"].min())
    previous_high = float(previous["high"].max())
    previous_low = float(previous["low"].min())
    if current_high > previous_high and current_low > previous_low:
        return 1.0
    if current_high < previous_high and current_low < previous_low:
        return -1.0
    return 0.0


def _normalized_component(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return float(np.tanh(value))


def _frame_components(
    frame: pd.DataFrame,
    index: int,
    *,
    prefix: str,
    slope_lag: int,
    return_lag: int,
) -> dict[str, float]:
    row = frame.iloc[index]
    close = float(row["close"])
    atr14 = float(row.get("atr14", np.nan))
    if not isfinite(atr14) or atr14 <= 0:
        return {
            f"{prefix}_close_ema20": 0.0,
            f"{prefix}_ema20_ema50": 0.0,
            f"{prefix}_ema20_slope": 0.0,
            f"{prefix}_return{return_lag}": 0.0,
            f"{prefix}_structure": 0.0,
        }

    ema20 = float(row.get("ema20", close))
    ema50 = float(row.get("ema50", ema20))
    slope_index = max(0, index - slope_lag)
    return_index = max(0, index - return_lag)
    ema20_lag = float(frame.iloc[slope_index].get("ema20", frame.iloc[slope_index]["close"]))
    close_lag = float(frame.iloc[return_index]["close"])

    return {
        f"{prefix}_close_ema20": _normalized_component((close - ema20) / atr14),
        f"{prefix}_ema20_ema50": _normalized_component((ema20 - ema50) / atr14),
        f"{prefix}_ema20_slope": _normalized_component((ema20 - ema20_lag) / atr14),
        f"{prefix}_return{return_lag}": _normalized_component((close - close_lag) / atr14),
        f"{prefix}_structure": _structure_component(frame, index),
    }


def _raw_score(
    *,
    h4: pd.DataFrame,
    h4_index: int,
    daily: pd.DataFrame,
    daily_index: int,
) -> tuple[float, dict[str, float]]:
    components = {}
    components.update(
        _frame_components(
            daily,
            daily_index,
            prefix="d1",
            slope_lag=3,
            return_lag=5,
        )
    )
    components.update(
        _frame_components(
            h4,
            h4_index,
            prefix="h4",
            slope_lag=4,
            return_lag=4,
        )
    )
    score = sum(
        COMPONENT_WEIGHTS[name] * components.get(name, 0.0)
        for name in COMPONENT_WEIGHTS
    )
    return float(np.clip(score, -1.0, 1.0)), components


def build_regime_points(bars: Sequence[Bar]) -> tuple[RegimePoint, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 5_000:
        return ()
    last_closed_at = ensure_utc(rows[-1].timestamp) + timedelta(minutes=15)

    h4 = _resample_completed(rows, "4h", as_of=last_closed_at)
    daily = _resample_completed(rows, "1D", as_of=last_closed_at)
    for frame in (h4, daily):
        frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
        frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
        frame["atr14"] = _atr(frame, 14)

    h4_times = _frame_times(h4)
    daily_times = _frame_times(daily)

    state = "NEUTRAL"
    pending_direction: str | None = None
    pending_count = 0
    neutral_count = 0
    points: list[RegimePoint] = []

    for h4_index in range(50, len(h4)):
        map_at = h4_times[h4_index]
        daily_index = _last_frame_index(daily_times, map_at)
        if daily_index is None or daily_index < 50:
            continue

        score, components = _raw_score(
            h4=h4,
            h4_index=h4_index,
            daily=daily,
            daily_index=daily_index,
        )
        raw = _direction_from_score(score)
        strong = abs(score) >= STRONG_SWITCH_THRESHOLD

        if state == "NEUTRAL":
            if raw in {"LONG", "SHORT"}:
                if pending_direction == raw:
                    pending_count += 1
                else:
                    pending_direction = raw
                    pending_count = 1
                if strong or pending_count >= SWITCH_CONFIRM_H4:
                    state = raw
                    pending_direction = None
                    pending_count = 0
                    neutral_count = 0
            else:
                pending_direction = None
                pending_count = 0
        elif raw == state:
            pending_direction = None
            pending_count = 0
            neutral_count = 0
        elif raw == "NEUTRAL":
            pending_direction = None
            pending_count = 0
            if abs(score) <= NEUTRALIZE_THRESHOLD:
                neutral_count += 1
                if neutral_count >= NEUTRAL_CONFIRM_H4:
                    state = "NEUTRAL"
                    neutral_count = 0
            else:
                neutral_count = 0
        else:
            neutral_count = 0
            if pending_direction == raw:
                pending_count += 1
            else:
                pending_direction = raw
                pending_count = 1
            if strong or pending_count >= SWITCH_CONFIRM_H4:
                state = raw
                pending_direction = None
                pending_count = 0

        h4_row = h4.iloc[h4_index]
        baseline = "LONG" if float(h4_row["close"]) > float(h4_row["open"]) else "SHORT"
        points.append(
            RegimePoint(
                map_at=map_at,
                close=float(h4_row["close"]),
                raw_score=score,
                raw_direction=raw,
                strategic_bias=state,
                baseline_h4_direction=baseline,
                switch_pending_direction=pending_direction,
                switch_pending_count=pending_count,
                neutral_pending_count=neutral_count,
                components=components,
            )
        )
    return tuple(points)


def _future_direction_metrics(
    points: Sequence[RegimePoint],
    *,
    source: str,
    horizon_h4: int,
    test_start: int,
) -> dict[str, Any]:
    universe = 0
    hits = 0
    signed_moves = []
    for index in range(test_start, len(points) - horizon_h4):
        point = points[index]
        direction = (
            point.strategic_bias
            if source == "strategic"
            else point.baseline_h4_direction
        )
        if direction not in {"LONG", "SHORT"}:
            continue
        future = points[index + horizon_h4]
        delta = float(future.close) - float(point.close)
        signed = delta if direction == "LONG" else -delta
        universe += 1
        hits += int(signed > 0)
        signed_moves.append(signed)
    return {
        "horizon_h4": horizon_h4,
        "coverage": universe,
        "hits": hits,
        "precision": None if universe == 0 else hits / universe,
        "wilson_lower_95": wilson_lower_bound(hits, universe),
        "mean_signed_move_points": None if not signed_moves else float(np.mean(signed_moves)),
        "median_signed_move_points": None if not signed_moves else float(np.median(signed_moves)),
    }


def _stability(points: Sequence[RegimePoint], *, test_start: int) -> dict[str, Any]:
    rows = points[test_start:]
    active = [row.strategic_bias for row in rows if row.strategic_bias in {"LONG", "SHORT"}]
    flips = sum(left != right for left, right in zip(active, active[1:]))
    baseline = [row.baseline_h4_direction for row in rows]
    baseline_flips = sum(left != right for left, right in zip(baseline, baseline[1:]))

    durations = []
    if active:
        current = active[0]
        count = 1
        for value in active[1:]:
            if value == current:
                count += 1
            else:
                durations.append(count)
                current = value
                count = 1
        durations.append(count)

    return {
        "strategic_active_points": len(active),
        "strategic_flips": flips,
        "strategic_flips_per_100_h4": None if len(active) < 2 else 100.0 * flips / (len(active) - 1),
        "baseline_h4_flips": baseline_flips,
        "baseline_h4_flips_per_100_h4": None if len(baseline) < 2 else 100.0 * baseline_flips / (len(baseline) - 1),
        "median_regime_duration_h4": None if not durations else float(median(durations)),
        "median_regime_duration_hours": None if not durations else float(median(durations) * 4.0),
    }


def _zone_distance(price: float, zone: OriginZone) -> float:
    if price < float(zone.low):
        return float(zone.low) - price
    if price > float(zone.high):
        return price - float(zone.high)
    return 0.0


def current_aligned_zone_pool(
    bars: Sequence[Bar],
    *,
    strategic_bias: str,
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    if not rows or strategic_bias not in {"LONG", "SHORT"}:
        return {
            "strategic_bias": strategic_bias,
            "canonical_0_24h": [],
            "shadow_24_48h": [],
            "canonical_count": 0,
            "shadow_count": 0,
        }

    last_closed_at = ensure_utc(rows[-1].timestamp) + timedelta(minutes=15)
    h4 = _resample_completed(rows, "4h", as_of=last_closed_at)
    if h4.empty:
        return {
            "strategic_bias": strategic_bias,
            "canonical_0_24h": [],
            "shadow_24_48h": [],
            "canonical_count": 0,
            "shadow_count": 0,
        }

    map_row = h4.iloc[-1]
    map_at = ensure_utc(map_row["time"].to_pydatetime())
    map_price = float(map_row["close"])
    zones = _origin_zones(rows, as_of=last_closed_at)
    canonical = []
    shadow = []

    for zone in zones:
        available_at = ensure_utc(zone.available_at)
        if available_at > map_at or zone.direction != strategic_bias:
            continue
        age_hours = (map_at - available_at).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > SHADOW_ZONE_MAX_AGE_HOURS:
            continue

        lifecycle = _zone_touch_lifecycle(zone, bars=rows, map_at=map_at)
        if bool(lifecycle.get("invalidated_before_map")):
            continue

        if strategic_bias == "SHORT" and float(zone.low) <= map_price:
            continue
        if strategic_bias == "LONG" and float(zone.high) >= map_price:
            continue

        payload = {
            "zone_id": _stable_zone_id(zone),
            "direction": zone.direction,
            "low": float(zone.low),
            "high": float(zone.high),
            "available_at": available_at.isoformat(),
            "origin_at": ensure_utc(zone.origin_at).isoformat(),
            "age_at_map_hours": age_hours,
            "distance_from_map_points": _zone_distance(map_price, zone),
            "displacement_range_atr": float(zone.displacement_range_atr),
            "displacement_body_fraction": float(zone.displacement_body_fraction),
            "touch_lifecycle": lifecycle.get("touch_lifecycle"),
            "zone_lifecycle": lifecycle.get("zone_lifecycle"),
            "auto_execution_authority": age_hours <= CANONICAL_ZONE_MAX_AGE_HOURS,
        }
        if age_hours <= CANONICAL_ZONE_MAX_AGE_HOURS:
            canonical.append(payload)
        else:
            payload["auto_execution_authority"] = False
            payload["research_only_reason"] = "AGE_24_TO_48H_SHADOW_POOL"
            shadow.append(payload)

    canonical.sort(key=lambda row: (float(row["distance_from_map_points"]), float(row["age_at_map_hours"])))
    shadow.sort(key=lambda row: (float(row["distance_from_map_points"]), float(row["age_at_map_hours"])))
    return {
        "strategic_bias": strategic_bias,
        "map_at": map_at.isoformat(),
        "map_price": map_price,
        "desired_reaction_side": "UPPER_SHORT_SUPPLY" if strategic_bias == "SHORT" else "LOWER_LONG_DEMAND",
        "tactical_first_leg": "LONG" if strategic_bias == "SHORT" else "SHORT",
        "canonical_0_24h": canonical[:5],
        "shadow_24_48h": shadow[:5],
        "canonical_count": len(canonical),
        "shadow_count": len(shadow),
    }


def evaluate_htf_regime_research(bars: Sequence[Bar]) -> dict[str, Any]:
    points = build_regime_points(bars)
    if len(points) < 100:
        return {
            "research_version": RESEARCH_VERSION,
            "artifact_contract": ARTIFACT_CONTRACT,
            "decision": "DATA_INSUFFICIENT",
            "points": len(points),
            "execution_influence": False,
        }

    test_start = int(len(points) * (1.0 - TEST_FRACTION))
    latest = points[-1]
    strategic_metrics = {
        "4h": _future_direction_metrics(points, source="strategic", horizon_h4=1, test_start=test_start),
        "8h": _future_direction_metrics(points, source="strategic", horizon_h4=2, test_start=test_start),
        "16h": _future_direction_metrics(points, source="strategic", horizon_h4=4, test_start=test_start),
    }
    baseline_metrics = {
        "4h": _future_direction_metrics(points, source="baseline", horizon_h4=1, test_start=test_start),
        "8h": _future_direction_metrics(points, source="baseline", horizon_h4=2, test_start=test_start),
        "16h": _future_direction_metrics(points, source="baseline", horizon_h4=4, test_start=test_start),
    }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "method": {
            "strategic_inputs": "COMPLETED_D1_AND_H4_ONLY",
            "score_range": [-1.0, 1.0],
            "raw_direction_threshold": RAW_DIRECTION_THRESHOLD,
            "strong_switch_threshold": STRONG_SWITCH_THRESHOLD,
            "switch_confirm_h4": SWITCH_CONFIRM_H4,
            "neutralize_threshold": NEUTRALIZE_THRESHOLD,
            "neutral_confirm_h4": NEUTRAL_CONFIRM_H4,
            "component_weights": COMPONENT_WEIGHTS,
            "baseline_comparator": "LAST_COMPLETED_H4_CANDLE_COLOR",
        },
        "points": len(points),
        "untouched_test_points": len(points) - test_start,
        "current": {
            "map_at": latest.map_at.isoformat(),
            "price": latest.close,
            "strategic_bias": latest.strategic_bias,
            "raw_direction": latest.raw_direction,
            "raw_score": latest.raw_score,
            "confidence": min(1.0, abs(latest.raw_score) / STRONG_SWITCH_THRESHOLD),
            "baseline_h4_direction": latest.baseline_h4_direction,
            "tactical_first_leg": (
                "LONG" if latest.strategic_bias == "SHORT"
                else "SHORT" if latest.strategic_bias == "LONG"
                else "NEUTRAL"
            ),
            "switch_pending_direction": latest.switch_pending_direction,
            "switch_pending_count": latest.switch_pending_count,
            "components": latest.components,
        },
        "untouched_test": {
            "strategic": strategic_metrics,
            "baseline_h4_candle": baseline_metrics,
            "stability": _stability(points, test_start=test_start),
        },
        "zone_pool": current_aligned_zone_pool(
            bars,
            strategic_bias=latest.strategic_bias,
        ),
        "decision": "SHADOW_VALIDATION_ONLY",
        "notes": [
            "Strategic bias uses completed D1/H4 information only and is intentionally sticky.",
            "A SHORT strategic bias means wait for price to rally into an upper SHORT supply/origin zone; tactical first leg can therefore be LONG.",
            "A LONG strategic bias means wait for price to decline into a lower LONG demand/origin zone; tactical first leg can therefore be SHORT.",
            "0-24h H1 origins remain the canonical AFIC execution pool.",
            "24-48h structurally active aligned H1 origins are exposed only as a shadow research pool.",
            "V180 does not change AFIC execution authority, Grade A/B rules, sizing, risk, or broker execution.",
        ],
    }

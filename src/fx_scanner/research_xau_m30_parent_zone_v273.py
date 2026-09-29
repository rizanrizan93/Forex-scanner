from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Sequence

import numpy as np

from .demo_xau_afic_path_shadow_observer import _resample_completed
from .demo_xau_supply_demand_atlas_v182 import (
    M30_SHADOW_RULE,
    SDZone,
    _approach_quality,
    _dedupe_zones,
    _detect_base_departure_zones,
    _overlap_ratio,
    _session_bucket_wib,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_supply_demand_reaction_v183 import (
    DEVELOPMENT_FRACTION,
    MAX_TOUCHES_PER_ZONE,
    _all_zones,
    _invalidated,
    _touch,
    evaluate_reaction_outcome,
)
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_M30_PARENT_ZONE_CALIBRATION_V273"
ARTIFACT_CONTRACT = "XAU_M30_PARENT_ZONE_CALIBRATION_V273_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

PRIMARY_REACTION_ATR = 0.50
REACTION_HORIZON_M15 = 32  # 8 hours after an M30 parent-zone touch.
OBSERVATION_HOURS = 24 * 7
PURGE_HOURS = 48
MIN_HOLDOUT_N = 30
DEPTH_BANDS = tuple((i / 10.0, (i + 1) / 10.0) for i in range(10))


@dataclass(frozen=True, slots=True)
class M30ParentEpisode:
    zone_id: str
    direction: str
    pattern: str
    touch_at: datetime
    touch_ordinal: int
    age_hours: float
    session_context: str
    approach_state: str
    low: float
    high: float
    width: float
    atr_points: float
    departure_range_atr: float
    departure_body_fraction: float
    base_range_atr: float
    parent_overlap_ratio: float
    parent_overlap_bucket: str
    parent_timeframe: str | None
    parent_zone_id: str | None
    max_depth_before_outcome: float
    reversal_depth_band: str | None
    outcome_status: str
    label_hold: bool
    bars_to_outcome: int | None
    mfe_atr: float
    mae_atr: float
    hit_025_before_break: bool
    hit_050_before_break: bool
    hit_075_before_break: bool
    hit_100_before_break: bool


def _age_bucket_m30(age_hours: float) -> str:
    hours = max(0.0, float(age_hours))
    if hours <= 12:
        return "M30_0_12H"
    if hours <= 24:
        return "M30_12_24H"
    if hours <= 48:
        return "M30_24_48H"
    return "M30_GT_48H"


def _overlap_bucket(value: float) -> str:
    ratio = max(0.0, min(1.0, float(value)))
    if ratio >= 0.70:
        return "HIGH_70_100"
    if ratio >= 0.30:
        return "MEDIUM_30_70"
    if ratio > 0.0:
        return "LOW_0_30"
    return "NONE"


def _depth_band_label(depth: float) -> str:
    value = max(0.0, min(1.0, float(depth)))
    index = min(9, int(value * 10.0))
    return f"{index * 10:02d}-{(index + 1) * 10:02d}%"


def _penetration_depth(zone: SDZone, row: Bar) -> float:
    width = max(float(zone.high) - float(zone.low), 1e-12)
    if zone.direction == "LONG":
        raw = (float(zone.high) - max(float(zone.low), float(row.low))) / width
    else:
        raw = (min(float(zone.high), float(row.high)) - float(zone.low)) / width
    return max(0.0, min(1.0, raw))


def _max_depth_until_outcome(
    rows: Sequence[Bar],
    *,
    touch_index: int,
    zone: SDZone,
    bars_to_outcome: int | None,
) -> float:
    end_offset = (
        REACTION_HORIZON_M15
        if bars_to_outcome is None
        else max(0, min(int(bars_to_outcome), REACTION_HORIZON_M15))
    )
    end = min(len(rows), touch_index + end_offset + 1)
    if end <= touch_index:
        return 0.0
    return max(
        _penetration_depth(zone, row)
        for row in rows[touch_index:end]
    )


def _invalidated_at(
    rows: Sequence[Bar],
    row_times: Sequence[datetime],
    zone: SDZone,
) -> datetime | None:
    start = bisect_left(row_times, ensure_utc(zone.available_at))
    for row in rows[start:]:
        if _invalidated(row, zone):
            return ensure_utc(row.timestamp)
    return None


def _best_parent(
    *,
    zone: SDZone,
    touch_at: datetime,
    canonical: Sequence[SDZone],
    invalidated_by_id: dict[str, datetime | None],
) -> tuple[float, SDZone | None]:
    matches: list[tuple[float, int, SDZone]] = []
    for parent in canonical:
        if parent.timeframe not in {"H1", "H4"}:
            continue
        if parent.direction != zone.direction:
            continue
        if ensure_utc(parent.available_at) > ensure_utc(touch_at):
            continue
        invalidated = invalidated_by_id.get(parent.zone_id)
        if invalidated is not None and ensure_utc(invalidated) <= ensure_utc(touch_at):
            continue
        overlap = _overlap_ratio(zone, parent)
        if overlap <= 0.0:
            continue
        priority = 2 if parent.timeframe == "H4" else 1
        matches.append((float(overlap), priority, parent))
    if not matches:
        return 0.0, None
    matches.sort(key=lambda item: (-item[0], -item[1], item[2].available_at))
    overlap, _, parent = matches[0]
    return overlap, parent


def _scan_touch_indices(
    rows: Sequence[Bar],
    row_times: Sequence[datetime],
    *,
    zone: SDZone,
) -> tuple[tuple[int, int], ...]:
    available = ensure_utc(zone.available_at)
    start = bisect_left(row_times, available)
    expiry = available + timedelta(hours=OBSERVATION_HOURS)
    end = min(len(rows), bisect_right(row_times, expiry))
    touches: list[tuple[int, int]] = []
    ordinal = 0
    was_inside = False
    next_eligible = start
    for index in range(start, end):
        row = rows[index]
        inside = _touch(row, zone)
        if inside and not was_inside:
            ordinal += 1
            if (
                ordinal <= MAX_TOUCHES_PER_ZONE
                and index >= next_eligible
                and index + REACTION_HORIZON_M15 < len(rows)
            ):
                touches.append((ordinal, index))
                next_eligible = index + REACTION_HORIZON_M15 + 1
        if _invalidated(row, zone):
            break
        was_inside = inside
    return tuple(touches)


def build_m30_parent_dataset(bars: Sequence[Bar]) -> tuple[M30ParentEpisode, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 20_000:
        return ()
    row_times = tuple(ensure_utc(row.timestamp) for row in rows)
    as_of = row_times[-1] + timedelta(minutes=15)

    m30 = _resample_completed(rows, M30_SHADOW_RULE, as_of=as_of)
    m30_zones = tuple(
        _dedupe_zones(_detect_base_departure_zones(m30, timeframe="M30"))
    )
    canonical = tuple(
        zone
        for zone in _all_zones(rows, as_of=as_of)
        if zone.timeframe in {"H1", "H4"}
    )
    invalidated_by_id = {
        zone.zone_id: _invalidated_at(rows, row_times, zone)
        for zone in canonical
    }

    episodes: list[M30ParentEpisode] = []
    for zone in m30_zones:
        for ordinal, touch_index in _scan_touch_indices(
            rows,
            row_times,
            zone=zone,
        ):
            outcome = evaluate_reaction_outcome(
                rows,
                touch_index=touch_index,
                zone=zone,
                horizon_m15=REACTION_HORIZON_M15,
                primary_reaction_atr=PRIMARY_REACTION_ATR,
            )
            if outcome.status == "PENDING":
                continue
            touch_at = ensure_utc(rows[touch_index].timestamp)
            overlap, parent = _best_parent(
                zone=zone,
                touch_at=touch_at,
                canonical=canonical,
                invalidated_by_id=invalidated_by_id,
            )
            prior = rows[max(0, touch_index - 12):touch_index]
            approach = _approach_quality(prior, zone=zone)
            max_depth = _max_depth_until_outcome(
                rows,
                touch_index=touch_index,
                zone=zone,
                bars_to_outcome=outcome.bars_to_outcome,
            )
            episodes.append(
                M30ParentEpisode(
                    zone_id=zone.zone_id,
                    direction=zone.direction,
                    pattern=zone.pattern,
                    touch_at=touch_at,
                    touch_ordinal=int(ordinal),
                    age_hours=max(
                        0.0,
                        (touch_at - ensure_utc(zone.available_at)).total_seconds()
                        / 3600.0,
                    ),
                    session_context=_session_bucket_wib(touch_at),
                    approach_state=str(approach.get("state") or "INSUFFICIENT"),
                    low=float(zone.low),
                    high=float(zone.high),
                    width=float(zone.high) - float(zone.low),
                    atr_points=float(zone.atr_points),
                    departure_range_atr=float(zone.departure_range_atr),
                    departure_body_fraction=float(zone.departure_body_fraction),
                    base_range_atr=float(zone.base_range_atr),
                    parent_overlap_ratio=float(overlap),
                    parent_overlap_bucket=_overlap_bucket(overlap),
                    parent_timeframe=None if parent is None else parent.timeframe,
                    parent_zone_id=None if parent is None else parent.zone_id,
                    max_depth_before_outcome=float(max_depth),
                    reversal_depth_band=(
                        _depth_band_label(max_depth)
                        if bool(outcome.label_hold)
                        else None
                    ),
                    outcome_status=str(outcome.status),
                    label_hold=bool(outcome.label_hold),
                    bars_to_outcome=outcome.bars_to_outcome,
                    mfe_atr=float(outcome.max_favorable_excursion_atr),
                    mae_atr=float(outcome.max_adverse_excursion_atr),
                    hit_025_before_break=bool(outcome.hit_025_before_break),
                    hit_050_before_break=bool(outcome.hit_050_before_break),
                    hit_075_before_break=bool(outcome.hit_075_before_break),
                    hit_100_before_break=bool(outcome.hit_100_before_break),
                )
            )
    episodes.sort(key=lambda row: (row.touch_at, row.zone_id, row.touch_ordinal))
    return tuple(episodes)


def _summary(rows: Sequence[M30ParentEpisode]) -> dict[str, Any]:
    selected = tuple(rows)
    n = len(selected)
    if not n:
        return {
            "n": 0,
            "hold_050": 0,
            "hold_050_rate": None,
            "wilson_lower_95": None,
            "breaks": 0,
        }
    holds = sum(row.label_hold for row in selected)
    breaks = sum(str(row.outcome_status).startswith("BREAK") for row in selected)
    return {
        "n": n,
        "hold_025_rate": sum(row.hit_025_before_break for row in selected) / n,
        "hold_050": int(holds),
        "hold_050_rate": holds / n,
        "hold_075_rate": sum(row.hit_075_before_break for row in selected) / n,
        "hold_100_rate": sum(row.hit_100_before_break for row in selected) / n,
        "wilson_lower_95": wilson_lower_bound(holds, n),
        "breaks": int(breaks),
        "break_rate": breaks / n,
        "median_mfe_atr": float(median(row.mfe_atr for row in selected)),
        "median_mae_atr": float(median(row.mae_atr for row in selected)),
        "median_depth_before_outcome": float(
            median(row.max_depth_before_outcome for row in selected)
        ),
    }


def _depth_hazard(rows: Sequence[M30ParentEpisode]) -> list[dict[str, Any]]:
    selected = tuple(rows)
    output: list[dict[str, Any]] = []
    for low, high in DEPTH_BANDS:
        at_risk = [
            row for row in selected
            if row.max_depth_before_outcome + 1e-12 >= low
        ]
        reversals = [
            row for row in at_risk
            if row.label_hold
            and low - 1e-12
            <= row.max_depth_before_outcome
            < high + (1e-12 if high >= 1.0 else 0.0)
        ]
        penetrated_next = [
            row for row in at_risk
            if row.max_depth_before_outcome + 1e-12 >= high
        ]
        n = len(at_risk)
        output.append(
            {
                "band": f"{int(low*100):02d}-{int(high*100):02d}%",
                "lower_depth": low,
                "upper_depth": high,
                "at_risk": n,
                "reversals_050": len(reversals),
                "hazard_050": None if not n else len(reversals) / n,
                "penetration_to_next": (
                    None if not n else len(penetrated_next) / n
                ),
                "wilson_lower_95": (
                    None
                    if not n
                    else wilson_lower_bound(len(reversals), n)
                ),
            }
        )
    return output


def _group_report(
    rows: Sequence[M30ParentEpisode],
    field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[M30ParentEpisode]] = {}
    for row in rows:
        value = (
            _age_bucket_m30(row.age_hours)
            if field == "age_bucket"
            else str(getattr(row, field))
        )
        groups.setdefault(value, []).append(row)
    output = [
        {"group": key, **_summary(members)}
        for key, members in groups.items()
    ]
    output.sort(
        key=lambda item: (
            -int(item.get("n") or 0),
            -float(item.get("hold_050_rate") or 0.0),
        )
    )
    return output


def _split_chronological(
    rows: Sequence[M30ParentEpisode],
) -> tuple[tuple[M30ParentEpisode, ...], tuple[M30ParentEpisode, ...]]:
    ordered = tuple(sorted(rows, key=lambda row: row.touch_at))
    times = sorted({row.touch_at for row in ordered})
    if len(times) < 30:
        return (), ()
    split_index = int(len(times) * DEVELOPMENT_FRACTION)
    if split_index <= 0 or split_index >= len(times):
        return (), ()
    split_at = times[split_index]
    purge = timedelta(hours=PURGE_HOURS)
    development = tuple(
        row for row in ordered if row.touch_at < split_at - purge
    )
    holdout = tuple(row for row in ordered if row.touch_at >= split_at)
    return development, holdout


def evaluate_m30_parent_calibration(bars: Sequence[Bar]) -> dict[str, Any]:
    episodes = build_m30_parent_dataset(bars)
    development, holdout = _split_chronological(episodes)
    base = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "episodes": len(episodes),
        "label_contract": {
            "parent_zone": "M30_BASE_DEPARTURE_SHADOW",
            "primary_reaction": "0.50_ATR_FAVORABLE_BEFORE_DISTAL_CLOSE_BREAK",
            "diagnostics_atr": [0.25, 0.50, 0.75, 1.00],
            "horizon_m15": REACTION_HORIZON_M15,
            "horizon_hours": REACTION_HORIZON_M15 * 0.25,
            "overlap_parent": "CAUSALLY_ACTIVE_H1_OR_H4_SAME_DIRECTION",
            "execution_authority": False,
        },
        "overall": _summary(episodes),
        "depth_hazard": _depth_hazard(episodes),
        "by_parent_overlap": _group_report(episodes, "parent_overlap_bucket"),
        "by_direction": _group_report(episodes, "direction"),
        "by_touch": _group_report(episodes, "touch_ordinal"),
        "by_age": _group_report(episodes, "age_bucket"),
        "by_approach": _group_report(episodes, "approach_state"),
        "by_session": _group_report(episodes, "session_context"),
        "split": {
            "development": len(development),
            "holdout": len(holdout),
            "development_fraction": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
        },
    }
    if not development or not holdout:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_M30_HOLDOUT",
            "development": {},
            "holdout": {},
            "holdout_overlap": [],
            "promotion_authority": False,
        }

    holdout_overlap = _group_report(holdout, "parent_overlap_bucket")
    high = next(
        (item for item in holdout_overlap if item["group"] == "HIGH_70_100"),
        None,
    )
    evidence_ready = bool(
        high
        and int(high.get("n") or 0) >= MIN_HOLDOUT_N
    )
    return base | {
        "decision": (
            "M30_PARENT_ZONE_EVIDENCE_READY_SHADOW_ONLY"
            if evidence_ready
            else "M30_PARENT_ZONE_MORE_EVIDENCE_REQUIRED"
        ),
        "development": _summary(development),
        "holdout": _summary(holdout),
        "holdout_depth_hazard": _depth_hazard(holdout),
        "holdout_overlap": holdout_overlap,
        "minimum_holdout_n": MIN_HOLDOUT_N,
        "promotion_authority": False,
        "note": (
            "V273 quantifies whether Afiq-style wide M30 parent zones add value "
            "beyond canonical H1/H4 overlap. No threshold is promoted to strict "
            "execution from this study."
        ),
    }

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_afic_path_shadow_observer import _resample_completed
from .demo_xau_supply_demand_atlas_v182 import (
    SDZone,
    TIMEFRAME_PRIORITY,
    TIMEFRAME_RULES,
    _age_bucket,
    _approach_quality,
    _dedupe_zones,
    _detect_base_departure_zones,
    _overlap_ratio,
    _session_bucket_wib,
    _structural_h1_zones,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_SUPPLY_DEMAND_REACTION_PROFILER_V183"
ARTIFACT_CONTRACT = "XAU_SUPPLY_DEMAND_REACTION_PROFILER_V183_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

PRIMARY_REACTION_ATR = 0.50
REACTION_HORIZON_M15 = 16
DIAGNOSTIC_REACTION_ATR = (0.25, 0.50, 0.75, 1.00)
MAX_TOUCHES_PER_ZONE = 4
PURGE_HOURS = 96
DEVELOPMENT_FRACTION = 0.70
MIN_HOLDOUT_SUBSET = 30
CLAIM_PRECISION = 0.80
LIQUIDITY_NEAR_ATR = 0.30

OBSERVATION_HOURS = {
    "H1": 24 * 10,
    "H4": 24 * 30,
    "D1": 24 * 90,
}

PRE_REGISTERED_GROUPS: tuple[tuple[str, ...], ...] = (
    ("timeframe", "zone_class", "pattern", "direction"),
    ("timeframe", "direction", "touch_bucket", "age_bucket"),
    ("timeframe", "direction", "nesting_bucket", "approach_state"),
    ("timeframe", "direction", "session_context"),
    ("timeframe", "direction", "liquidity_bucket"),
)


@dataclass(frozen=True, slots=True)
class ReactionOutcome:
    status: str
    label_hold: bool
    touch_at: datetime
    outcome_at: datetime | None
    bars_to_outcome: int | None
    max_favorable_excursion_atr: float
    max_adverse_excursion_atr: float
    hit_025_before_break: bool
    hit_050_before_break: bool
    hit_075_before_break: bool
    hit_100_before_break: bool


@dataclass(frozen=True, slots=True)
class ZoneDestination:
    zone_id: str
    timeframe: str
    zone_class: str
    pattern: str
    direction: str
    available_at: datetime
    low: float
    high: float
    atr_points: float
    observation_hours: int
    touched: bool
    first_touch_at: datetime | None
    invalidated_at: datetime | None
    expired_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReactionEpisode:
    zone_id: str
    timeframe: str
    zone_class: str
    pattern: str
    direction: str
    available_at: datetime
    touch_at: datetime
    touch_ordinal: int
    touch_bucket: str
    age_hours: float
    age_bucket: str
    session_context: str
    approach_state: str
    htf_nesting_count: int
    nesting_bucket: str
    liquidity_sources: tuple[str, ...]
    liquidity_bucket: str
    departure_range_atr: float
    departure_body_fraction: float
    base_range_atr: float
    structural_bos: bool
    outcome: ReactionOutcome


def _touch(row: Bar, zone: SDZone) -> bool:
    return float(row.low) <= float(zone.high) and float(row.high) >= float(zone.low)


def _invalidated(row: Bar, zone: SDZone) -> bool:
    if zone.direction == "LONG":
        return float(row.close) < float(zone.distal)
    return float(row.close) > float(zone.distal)


def _favorable_excursion(row: Bar, zone: SDZone) -> float:
    if zone.direction == "LONG":
        return max(0.0, float(row.high) - float(zone.high))
    return max(0.0, float(zone.low) - float(row.low))


def _adverse_excursion(row: Bar, zone: SDZone) -> float:
    if zone.direction == "LONG":
        return max(0.0, float(zone.high) - float(row.low))
    return max(0.0, float(row.high) - float(zone.low))


def evaluate_reaction_outcome(
    bars: Sequence[Bar],
    *,
    touch_index: int,
    zone: SDZone,
    horizon_m15: int = REACTION_HORIZON_M15,
    primary_reaction_atr: float = PRIMARY_REACTION_ATR,
) -> ReactionOutcome:
    rows = tuple(bars)
    if not (0 <= touch_index < len(rows)):
        raise ValueError("V183_TOUCH_INDEX_INVALID")
    if zone.direction not in {"LONG", "SHORT"}:
        raise ValueError("V183_DIRECTION_INVALID")
    atr = float(zone.atr_points)
    if not isfinite(atr) or atr <= 0:
        raise ValueError("V183_ATR_INVALID")
    if not isfinite(primary_reaction_atr) or primary_reaction_atr <= 0:
        raise ValueError("V183_PRIMARY_REACTION_INVALID")

    touch = rows[touch_index]
    touch_at = ensure_utc(touch.timestamp)
    max_favorable = 0.0
    max_adverse = _adverse_excursion(touch, zone)
    hits = {threshold: False for threshold in DIAGNOSTIC_REACTION_ATR}

    # Conservative ambiguity contract: close beyond distal wins on the touch bar.
    if _invalidated(touch, zone):
        return ReactionOutcome(
            status="BREAK_TOUCH_BAR",
            label_hold=False,
            touch_at=touch_at,
            outcome_at=touch_at,
            bars_to_outcome=0,
            max_favorable_excursion_atr=0.0,
            max_adverse_excursion_atr=max_adverse / atr,
            hit_025_before_break=False,
            hit_050_before_break=False,
            hit_075_before_break=False,
            hit_100_before_break=False,
        )

    primary_hold_at: datetime | None = None
    primary_hold_offset: int | None = None
    break_at: datetime | None = None
    break_offset: int | None = None

    future = rows[touch_index + 1 : touch_index + 1 + int(horizon_m15)]
    for offset, row in enumerate(future, start=1):
        max_adverse = max(max_adverse, _adverse_excursion(row, zone))
        # Break wins same-bar ambiguity. Do not count a threshold first reached
        # inside the same candle whose close structurally invalidates the zone.
        if _invalidated(row, zone):
            break_at = ensure_utc(row.timestamp)
            break_offset = offset
            break

        max_favorable = max(max_favorable, _favorable_excursion(row, zone))
        favorable_atr = max_favorable / atr
        for threshold in DIAGNOSTIC_REACTION_ATR:
            if favorable_atr + 1e-12 >= threshold:
                hits[threshold] = True
        if (
            primary_hold_at is None
            and favorable_atr + 1e-12 >= float(primary_reaction_atr)
        ):
            primary_hold_at = ensure_utc(row.timestamp)
            primary_hold_offset = offset

    if primary_hold_at is not None and (
        break_at is None or primary_hold_at < break_at
    ):
        status = "HOLD"
        label_hold = True
        outcome_at = primary_hold_at
        bars_to_outcome = primary_hold_offset
    elif break_at is not None:
        status = "BREAK"
        label_hold = False
        outcome_at = break_at
        bars_to_outcome = break_offset
    elif len(future) < int(horizon_m15):
        status = "PENDING"
        label_hold = False
        outcome_at = None
        bars_to_outcome = None
    else:
        status = "STALL"
        label_hold = False
        outcome_at = ensure_utc(future[-1].timestamp)
        bars_to_outcome = int(horizon_m15)

    return ReactionOutcome(
        status=status,
        label_hold=label_hold,
        touch_at=touch_at,
        outcome_at=outcome_at,
        bars_to_outcome=bars_to_outcome,
        max_favorable_excursion_atr=max_favorable / atr,
        max_adverse_excursion_atr=max_adverse / atr,
        hit_025_before_break=bool(hits[0.25]),
        hit_050_before_break=bool(hits[0.50]),
        hit_075_before_break=bool(hits[0.75]),
        hit_100_before_break=bool(hits[1.00]),
    )


def _touch_bucket(ordinal: int) -> str:
    if ordinal <= 1:
        return "FIRST_TEST"
    if ordinal == 2:
        return "SECOND_TEST"
    return "MULTI_TESTED"


def _nesting_bucket(count: int) -> str:
    if count <= 0:
        return "NO_HTF_NESTING"
    if count == 1:
        return "ONE_HTF_PARENT"
    return "MULTI_HTF_NESTING"


def _liquidity_bucket(count: int) -> str:
    if count <= 0:
        return "NO_LIQUIDITY_CONFLUENCE"
    if count == 1:
        return "ONE_LIQUIDITY_CONFLUENCE"
    return "MULTI_LIQUIDITY_CONFLUENCE"


def _frame_times(frame: pd.DataFrame) -> tuple[datetime, ...]:
    return tuple(ensure_utc(value.to_pydatetime()) for value in frame["time"])


def _last_frame_row(
    frame: pd.DataFrame,
    times: Sequence[datetime],
    timestamp: datetime,
):
    if frame.empty:
        return None
    index = bisect_right(times, ensure_utc(timestamp)) - 1
    return None if index < 0 else frame.iloc[index]


def _liquidity_sources(
    *,
    zone: SDZone,
    touch_at: datetime,
    daily: pd.DataFrame,
    daily_times: Sequence[datetime],
    weekly: pd.DataFrame,
    weekly_times: Sequence[datetime],
) -> tuple[str, ...]:
    atr = max(float(zone.atr_points), 1e-12)
    boundary = float(zone.proximal)
    threshold = LIQUIDITY_NEAR_ATR * atr
    role = "LOW" if zone.direction == "LONG" else "HIGH"
    sources: list[str] = []

    round_level = round(boundary / 10.0) * 10.0
    if abs(round_level - boundary) <= threshold:
        sources.append("ROUND_NUMBER")

    daily_row = _last_frame_row(daily, daily_times, touch_at)
    if daily_row is not None:
        price = float(daily_row["low"] if role == "LOW" else daily_row["high"])
        if abs(price - boundary) <= threshold:
            sources.append(f"PREVIOUS_DAY_{role}")

    weekly_row = _last_frame_row(weekly, weekly_times, touch_at)
    if weekly_row is not None:
        price = float(weekly_row["low"] if role == "LOW" else weekly_row["high"])
        if abs(price - boundary) <= threshold:
            sources.append(f"PREVIOUS_WEEK_{role}")

    return tuple(sorted(set(sources)))


def _all_zones(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[SDZone, ...]:
    zones: list[SDZone] = list(_structural_h1_zones(rows, as_of=as_of))
    for timeframe, rule in TIMEFRAME_RULES.items():
        frame = _resample_completed(rows, rule, as_of=as_of)
        zones.extend(_detect_base_departure_zones(frame, timeframe=timeframe))
    return _dedupe_zones(zones)


def _scan_zone(
    rows: Sequence[Bar],
    row_times: Sequence[datetime],
    *,
    zone: SDZone,
) -> tuple[ZoneDestination, list[tuple[int, ReactionOutcome, dict[str, Any]]]]:
    available = ensure_utc(zone.available_at)
    start = bisect_left(row_times, available)
    observation_hours = int(OBSERVATION_HOURS.get(zone.timeframe, 24 * 10))
    expiry = available + timedelta(hours=observation_hours)
    end = min(len(rows), bisect_right(row_times, expiry))

    first_touch_at: datetime | None = None
    invalidated_at: datetime | None = None
    touch_ordinal = 0
    was_inside = False
    next_eligible_touch_index = start
    raw_episodes: list[tuple[int, ReactionOutcome, dict[str, Any]]] = []

    for index in range(start, end):
        row = rows[index]
        inside = _touch(row, zone)
        if inside and not was_inside:
            touch_ordinal += 1
            if first_touch_at is None:
                first_touch_at = ensure_utc(row.timestamp)
            if (
                touch_ordinal <= MAX_TOUCHES_PER_ZONE
                and index >= next_eligible_touch_index
            ):
                outcome = evaluate_reaction_outcome(
                    rows,
                    touch_index=index,
                    zone=zone,
                )
                if outcome.status != "PENDING":
                    prior = rows[max(0, index - 12) : index]
                    approach = _approach_quality(prior, zone=zone)
                    raw_episodes.append(
                        (
                            touch_ordinal,
                            outcome,
                            {
                                "touch_index": index,
                                "approach_state": str(
                                    approach.get("state") or "INSUFFICIENT"
                                ),
                            },
                        )
                    )
                    lag = (
                        int(outcome.bars_to_outcome)
                        if outcome.bars_to_outcome is not None
                        else REACTION_HORIZON_M15
                    )
                    next_eligible_touch_index = index + max(1, lag) + 1

        if _invalidated(row, zone):
            invalidated_at = ensure_utc(row.timestamp)
            break
        was_inside = inside

    destination = ZoneDestination(
        zone_id=zone.zone_id,
        timeframe=zone.timeframe,
        zone_class=zone.zone_class,
        pattern=zone.pattern,
        direction=zone.direction,
        available_at=available,
        low=float(zone.low),
        high=float(zone.high),
        atr_points=float(zone.atr_points),
        observation_hours=observation_hours,
        touched=first_touch_at is not None,
        first_touch_at=first_touch_at,
        invalidated_at=invalidated_at,
        expired_at=expiry,
    )
    return destination, raw_episodes


def _parent_nesting_count(
    *,
    zone: SDZone,
    touch_at: datetime,
    zones_by_id: dict[str, SDZone],
    destinations_by_id: dict[str, ZoneDestination],
) -> int:
    midpoint = (float(zone.low) + float(zone.high)) / 2.0
    current_priority = TIMEFRAME_PRIORITY.get(zone.timeframe, 0)
    count = 0
    for parent in zones_by_id.values():
        if parent.zone_id == zone.zone_id:
            continue
        if parent.direction != zone.direction:
            continue
        if TIMEFRAME_PRIORITY.get(parent.timeframe, 0) <= current_priority:
            continue
        if ensure_utc(parent.available_at) > ensure_utc(touch_at):
            continue
        parent_destination = destinations_by_id.get(parent.zone_id)
        if parent_destination is None:
            continue
        invalidated_at = parent_destination.invalidated_at
        if invalidated_at is not None and ensure_utc(invalidated_at) <= ensure_utc(touch_at):
            continue
        if (
            float(parent.low) <= midpoint <= float(parent.high)
            or _overlap_ratio(zone, parent) > 0
        ):
            count += 1
    return count


def build_reaction_dataset(
    bars: Sequence[Bar],
) -> tuple[tuple[ZoneDestination, ...], tuple[ReactionEpisode, ...]]:
    rows = _validate_bars(bars)
    if len(rows) < 20_000:
        return (), ()
    row_times = tuple(ensure_utc(row.timestamp) for row in rows)
    as_of = row_times[-1] + timedelta(minutes=15)
    zones = _all_zones(rows, as_of=as_of)
    zones_by_id = {zone.zone_id: zone for zone in zones}

    daily = _resample_completed(rows, "1D", as_of=as_of)
    weekly = _resample_completed(rows, "W-MON", as_of=as_of)
    daily_times = _frame_times(daily)
    weekly_times = _frame_times(weekly)

    destinations: list[ZoneDestination] = []
    raw_by_zone: dict[str, list[tuple[int, ReactionOutcome, dict[str, Any]]]] = {}
    for zone in zones:
        destination, raw = _scan_zone(rows, row_times, zone=zone)
        destinations.append(destination)
        raw_by_zone[zone.zone_id] = raw

    destinations_by_id = {row.zone_id: row for row in destinations}
    episodes: list[ReactionEpisode] = []

    for zone in zones:
        for ordinal, outcome, metadata in raw_by_zone.get(zone.zone_id, []):
            touch_at = ensure_utc(outcome.touch_at)
            age_hours = max(
                0.0,
                (touch_at - ensure_utc(zone.available_at)).total_seconds() / 3600.0,
            )
            nesting_count = _parent_nesting_count(
                zone=zone,
                touch_at=touch_at,
                zones_by_id=zones_by_id,
                destinations_by_id=destinations_by_id,
            )
            liquidity = _liquidity_sources(
                zone=zone,
                touch_at=touch_at,
                daily=daily,
                daily_times=daily_times,
                weekly=weekly,
                weekly_times=weekly_times,
            )
            episodes.append(
                ReactionEpisode(
                    zone_id=zone.zone_id,
                    timeframe=zone.timeframe,
                    zone_class=zone.zone_class,
                    pattern=zone.pattern,
                    direction=zone.direction,
                    available_at=ensure_utc(zone.available_at),
                    touch_at=touch_at,
                    touch_ordinal=int(ordinal),
                    touch_bucket=_touch_bucket(int(ordinal)),
                    age_hours=age_hours,
                    age_bucket=_age_bucket(zone.timeframe, age_hours),
                    session_context=_session_bucket_wib(touch_at),
                    approach_state=str(metadata.get("approach_state") or "INSUFFICIENT"),
                    htf_nesting_count=nesting_count,
                    nesting_bucket=_nesting_bucket(nesting_count),
                    liquidity_sources=liquidity,
                    liquidity_bucket=_liquidity_bucket(len(liquidity)),
                    departure_range_atr=float(zone.departure_range_atr),
                    departure_body_fraction=float(zone.departure_body_fraction),
                    base_range_atr=float(zone.base_range_atr),
                    structural_bos=bool(zone.structural_bos),
                    outcome=outcome,
                )
            )

    destinations.sort(key=lambda row: (row.available_at, row.zone_id))
    episodes.sort(key=lambda row: (row.touch_at, row.zone_id, row.touch_ordinal))
    return tuple(destinations), tuple(episodes)


def _summary(rows: Sequence[ReactionEpisode]) -> dict[str, Any]:
    selected = tuple(rows)
    n = len(selected)
    if not n:
        return {
            "n": 0,
            "holds": 0,
            "breaks": 0,
            "stalls": 0,
            "precision_hold": None,
            "wilson_lower_95": None,
        }
    holds = sum(row.outcome.label_hold for row in selected)
    breaks = sum(row.outcome.status.startswith("BREAK") for row in selected)
    stalls = sum(row.outcome.status == "STALL" for row in selected)
    mfe = [row.outcome.max_favorable_excursion_atr for row in selected]
    mae = [row.outcome.max_adverse_excursion_atr for row in selected]
    decisive_bars = [
        int(row.outcome.bars_to_outcome)
        for row in selected
        if row.outcome.bars_to_outcome is not None
    ]
    return {
        "n": n,
        "holds": int(holds),
        "breaks": int(breaks),
        "stalls": int(stalls),
        "precision_hold": holds / n,
        "wilson_lower_95": wilson_lower_bound(int(holds), n),
        "hit_025": sum(row.outcome.hit_025_before_break for row in selected) / n,
        "hit_050": sum(row.outcome.hit_050_before_break for row in selected) / n,
        "hit_075": sum(row.outcome.hit_075_before_break for row in selected) / n,
        "hit_100": sum(row.outcome.hit_100_before_break for row in selected) / n,
        "mean_mfe_atr": float(np.mean(mfe)),
        "median_mfe_atr": float(median(mfe)),
        "mean_mae_atr": float(np.mean(mae)),
        "median_mae_atr": float(median(mae)),
        "p75_mae_atr": float(np.quantile(np.asarray(mae, dtype=float), 0.75)),
        "median_bars_to_outcome": None
        if not decisive_bars
        else float(median(decisive_bars)),
    }


def _destination_summary(rows: Sequence[ZoneDestination]) -> dict[str, Any]:
    selected = tuple(rows)
    if not selected:
        return {
            "zones": 0,
            "touched": 0,
            "touch_rate": None,
            "invalidated_before_or_at_window": 0,
        }
    touched = sum(row.touched for row in selected)
    invalidated = sum(row.invalidated_at is not None for row in selected)
    return {
        "zones": len(selected),
        "touched": int(touched),
        "touch_rate": touched / len(selected),
        "invalidated_before_or_at_window": int(invalidated),
    }


def _split_chronological(
    rows: Sequence[ReactionEpisode],
) -> tuple[tuple[ReactionEpisode, ...], tuple[ReactionEpisode, ...]]:
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


def _group_key(row: ReactionEpisode, fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(getattr(row, field)) for field in fields)


def _group_report(
    rows: Sequence[ReactionEpisode],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[ReactionEpisode]] = {}
    for row in rows:
        groups.setdefault(_group_key(row, fields), []).append(row)
    output: list[dict[str, Any]] = []
    for key, members in groups.items():
        metrics = _summary(members)
        output.append(
            {
                "dimensions": dict(zip(fields, key)),
                **metrics,
            }
        )
    output.sort(
        key=lambda item: (
            -int(item.get("n") or 0),
            -float(item.get("precision_hold") or 0.0),
        )
    )
    return output


def _candidate_subsets(
    holdout: Sequence[ReactionEpisode],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for fields in PRE_REGISTERED_GROUPS:
        for row in _group_report(holdout, fields):
            n = int(row.get("n") or 0)
            precision = row.get("precision_hold")
            if (
                n >= MIN_HOLDOUT_SUBSET
                and precision is not None
                and float(precision) >= CLAIM_PRECISION
            ):
                candidates.append(
                    {
                        "group_contract": list(fields),
                        **row,
                        "promotion_authority": False,
                        "interpretation": "EXPLORATORY_HOLDOUT_SUBSET_NOT_PRODUCTION_CLAIM",
                    }
                )
    candidates.sort(
        key=lambda item: (
            -float(item.get("wilson_lower_95") or 0.0),
            -int(item.get("n") or 0),
            -float(item.get("precision_hold") or 0.0),
        )
    )
    return candidates[:25]


def _destination_groups(
    destinations: Sequence[ZoneDestination],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[ZoneDestination]] = {}
    for row in destinations:
        key = (row.timeframe, row.zone_class, row.pattern, row.direction)
        groups.setdefault(key, []).append(row)
    output = []
    for key, members in groups.items():
        output.append(
            {
                "dimensions": {
                    "timeframe": key[0],
                    "zone_class": key[1],
                    "pattern": key[2],
                    "direction": key[3],
                },
                **_destination_summary(members),
            }
        )
    output.sort(key=lambda item: -int(item.get("zones") or 0))
    return output


def evaluate_supply_demand_research(bars: Sequence[Bar]) -> dict[str, Any]:
    destinations, episodes = build_reaction_dataset(bars)
    development, holdout = _split_chronological(episodes)

    base: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "label_contract": {
            "zone_population": "V182_STRUCTURAL_H1_PLUS_D1_H4_H1_BASE_DEPARTURE_IMBALANCE",
            "destination_window_hours": OBSERVATION_HOURS,
            "touch_definition": "FIRST_M15_OVERLAP_AFTER_ZONE_AVAILABLE_THEN_NON_OVERLAPPING_RETESTS",
            "primary_hold": "0.50_ATR_FAVORABLE_EXCURSION_WITHIN_16_M15_BEFORE_DISTAL_BREAK",
            "break": "M15_CLOSE_BEYOND_DISTAL_BEFORE_PRIMARY_HOLD; BREAK_WINS_SAME_BAR",
            "stall": "NEITHER_PRIMARY_HOLD_NOR_BREAK_WITHIN_16_M15",
            "diagnostic_thresholds_atr": list(DIAGNOSTIC_REACTION_ATR),
            "historical_spread": "EXCLUDED",
            "score_or_probability_fitted": False,
        },
        "zones": len(destinations),
        "episodes": len(episodes),
        "destination_overall": _destination_summary(destinations),
        "destination_by_zone_type": _destination_groups(destinations),
        "reaction_overall": _summary(episodes),
        "split": {
            "development": len(development),
            "holdout": len(holdout),
            "development_fraction": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
        },
        "pre_registered_group_contracts": [list(row) for row in PRE_REGISTERED_GROUPS],
    }

    if not development or not holdout:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_CAUSAL_HOLDOUT",
            "development_groups": {},
            "holdout_groups": {},
            "candidate_80_precision_subsets": [],
        }

    development_groups = {
        "|".join(fields): _group_report(development, fields)
        for fields in PRE_REGISTERED_GROUPS
    }
    holdout_groups = {
        "|".join(fields): _group_report(holdout, fields)
        for fields in PRE_REGISTERED_GROUPS
    }
    candidates = _candidate_subsets(holdout)

    decision = (
        "HISTORICAL_80_PRECISION_SUBSETS_FOUND_NOT_PROMOTED"
        if candidates
        else "NO_80_PERCENT_HOLDOUT_SUBSET_AT_SAMPLE_FLOOR"
    )
    return base | {
        "decision": decision,
        "development_overall": _summary(development),
        "holdout_overall": _summary(holdout),
        "development_groups": development_groups,
        "holdout_groups": holdout_groups,
        "candidate_80_precision_subsets": candidates,
        "candidate_policy": {
            "minimum_holdout_n": MIN_HOLDOUT_SUBSET,
            "minimum_raw_precision": CLAIM_PRECISION,
            "multiple_testing_note": (
                "Only pre-registered grouping contracts are scanned. Candidate subsets "
                "remain exploratory and require prospective validation before any policy change."
            ),
            "automatic_promotion": False,
        },
    }

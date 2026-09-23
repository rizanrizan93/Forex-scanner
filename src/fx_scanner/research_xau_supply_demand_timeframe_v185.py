from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Sequence

import numpy as np

from .demo_xau_afic_path_shadow_observer import _resample_completed
from .demo_xau_supply_demand_atlas_v182 import (
    SDZone,
    TIMEFRAME_PRIORITY,
    _age_bucket,
    _approach_quality,
    _overlap_ratio,
    _session_bucket_wib,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_supply_demand_reaction_v183 import (
    DEVELOPMENT_FRACTION,
    MAX_TOUCHES_PER_ZONE,
    PRIMARY_REACTION_ATR,
    _all_zones,
    _frame_times,
    _invalidated,
    _liquidity_bucket,
    _liquidity_sources,
    _nesting_bucket,
    _touch,
    _touch_bucket,
    evaluate_reaction_outcome,
)
from .research_xau_zone_path_v174 import wilson_lower_bound

RESEARCH_VERSION = "XAU_SUPPLY_DEMAND_TIMEFRAME_AWARE_V185"
ARTIFACT_CONTRACT = "XAU_SUPPLY_DEMAND_TIMEFRAME_AWARE_V185_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

PRIMARY_HORIZON_M15 = {
    "H1": 16,   # 4 hours
    "H4": 96,   # 24 hours
    "D1": 288,  # 72 hours
}
SENSITIVITY_HORIZONS_M15 = {
    "H1": (16,),
    "H4": (64, 96),         # 16h / 24h
    "D1": (192, 288, 480),  # 48h / 72h / 120h
}
OBSERVATION_HOURS = {
    "H1": 24 * 10,
    "H4": 24 * 30,
    "D1": 24 * 90,
}
PURGE_HOURS = 144
MIN_HOLDOUT_GROUP_N = 30
CLAIM_PRECISION = 0.80

PRE_REGISTERED_GROUPS: tuple[tuple[str, ...], ...] = (
    ("timeframe", "zone_class", "pattern", "direction"),
    ("timeframe", "direction", "touch_bucket", "age_bucket"),
    ("timeframe", "direction", "nesting_bucket", "approach_state"),
    ("timeframe", "direction", "session_context"),
    ("timeframe", "direction", "liquidity_bucket"),
)


@dataclass(frozen=True, slots=True)
class TimeframeEpisode:
    zone_id: str
    timeframe: str
    zone_class: str
    pattern: str
    direction: str
    available_at: datetime
    touch_at: datetime
    touch_index: int
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
    primary_horizon_m15: int
    primary_outcome: Any
    sensitivity: tuple[tuple[int, Any], ...]


def _active_at(
    zone: SDZone,
    *,
    rows: Sequence[Bar],
    timestamp: datetime,
) -> bool:
    cutoff = ensure_utc(timestamp)
    if ensure_utc(zone.available_at) > cutoff:
        return False
    for row in rows:
        ts = ensure_utc(row.timestamp)
        if ts < ensure_utc(zone.available_at):
            continue
        if ts > cutoff:
            break
        if _invalidated(row, zone):
            return False
    return True


def _parent_nesting_count(
    *,
    zone: SDZone,
    touch_at: datetime,
    zones: Sequence[SDZone],
    rows: Sequence[Bar],
) -> int:
    midpoint = (float(zone.low) + float(zone.high)) / 2.0
    current_priority = TIMEFRAME_PRIORITY.get(zone.timeframe, 0)
    count = 0
    for parent in zones:
        if parent.zone_id == zone.zone_id:
            continue
        if parent.direction != zone.direction:
            continue
        if TIMEFRAME_PRIORITY.get(parent.timeframe, 0) <= current_priority:
            continue
        if ensure_utc(parent.available_at) > ensure_utc(touch_at):
            continue
        if not _active_at(parent, rows=rows, timestamp=touch_at):
            continue
        if (
            float(parent.low) <= midpoint <= float(parent.high)
            or _overlap_ratio(zone, parent) > 0
        ):
            count += 1
    return count


def _scan_touch_indices(
    rows: Sequence[Bar],
    row_times: Sequence[datetime],
    *,
    zone: SDZone,
) -> tuple[int, ...]:
    available = ensure_utc(zone.available_at)
    start = bisect_left(row_times, available)
    expiry = available + timedelta(
        hours=int(OBSERVATION_HOURS.get(zone.timeframe, 24 * 10))
    )
    end = min(len(rows), bisect_right(row_times, expiry))
    max_horizon = max(SENSITIVITY_HORIZONS_M15.get(zone.timeframe, (16,)))

    touches: list[int] = []
    was_inside = False
    next_eligible = start
    ordinal = 0
    for index in range(start, end):
        row = rows[index]
        inside = _touch(row, zone)
        if inside and not was_inside:
            ordinal += 1
            if ordinal <= MAX_TOUCHES_PER_ZONE and index >= next_eligible:
                # Right-edge unresolved touches are excluded rather than labelled.
                if index + max_horizon < len(rows):
                    touches.append(index)
                    next_eligible = index + max_horizon + 1
        if _invalidated(row, zone):
            break
        was_inside = inside
    return tuple(touches)


def build_timeframe_dataset(
    bars: Sequence[Bar],
) -> tuple[TimeframeEpisode, ...]:
    rows = _validate_bars(bars)
    if len(rows) < 20_000:
        return ()
    row_times = tuple(ensure_utc(row.timestamp) for row in rows)
    as_of = row_times[-1] + timedelta(minutes=15)
    zones = _all_zones(rows, as_of=as_of)

    daily = _resample_completed(rows, "1D", as_of=as_of)
    weekly = _resample_completed(rows, "W-MON", as_of=as_of)
    daily_times = _frame_times(daily)
    weekly_times = _frame_times(weekly)

    episodes: list[TimeframeEpisode] = []
    for zone in zones:
        if zone.timeframe not in PRIMARY_HORIZON_M15:
            continue
        touch_indices = _scan_touch_indices(
            rows,
            row_times,
            zone=zone,
        )
        for local_ordinal, touch_index in enumerate(touch_indices, start=1):
            touch_at = ensure_utc(rows[touch_index].timestamp)
            primary_horizon = PRIMARY_HORIZON_M15[zone.timeframe]
            primary = evaluate_reaction_outcome(
                rows,
                touch_index=touch_index,
                zone=zone,
                horizon_m15=primary_horizon,
                primary_reaction_atr=PRIMARY_REACTION_ATR,
            )
            if primary.status == "PENDING":
                continue
            sensitivity = []
            for horizon in SENSITIVITY_HORIZONS_M15[zone.timeframe]:
                outcome = (
                    primary
                    if horizon == primary_horizon
                    else evaluate_reaction_outcome(
                        rows,
                        touch_index=touch_index,
                        zone=zone,
                        horizon_m15=horizon,
                        primary_reaction_atr=PRIMARY_REACTION_ATR,
                    )
                )
                if outcome.status != "PENDING":
                    sensitivity.append((int(horizon), outcome))

            prior = rows[max(0, touch_index - 12) : touch_index]
            approach = _approach_quality(prior, zone=zone)
            nesting_count = _parent_nesting_count(
                zone=zone,
                touch_at=touch_at,
                zones=zones,
                rows=rows,
            )
            liquidity = _liquidity_sources(
                zone=zone,
                touch_at=touch_at,
                daily=daily,
                daily_times=daily_times,
                weekly=weekly,
                weekly_times=weekly_times,
            )
            age_hours = max(
                0.0,
                (
                    touch_at - ensure_utc(zone.available_at)
                ).total_seconds()
                / 3600.0,
            )
            episodes.append(
                TimeframeEpisode(
                    zone_id=zone.zone_id,
                    timeframe=zone.timeframe,
                    zone_class=zone.zone_class,
                    pattern=zone.pattern,
                    direction=zone.direction,
                    available_at=ensure_utc(zone.available_at),
                    touch_at=touch_at,
                    touch_index=int(touch_index),
                    touch_ordinal=int(local_ordinal),
                    touch_bucket=_touch_bucket(int(local_ordinal)),
                    age_hours=age_hours,
                    age_bucket=_age_bucket(zone.timeframe, age_hours),
                    session_context=_session_bucket_wib(touch_at),
                    approach_state=str(
                        approach.get("state") or "INSUFFICIENT"
                    ),
                    htf_nesting_count=int(nesting_count),
                    nesting_bucket=_nesting_bucket(nesting_count),
                    liquidity_sources=liquidity,
                    liquidity_bucket=_liquidity_bucket(len(liquidity)),
                    departure_range_atr=float(zone.departure_range_atr),
                    departure_body_fraction=float(
                        zone.departure_body_fraction
                    ),
                    base_range_atr=float(zone.base_range_atr),
                    structural_bos=bool(zone.structural_bos),
                    primary_horizon_m15=int(primary_horizon),
                    primary_outcome=primary,
                    sensitivity=tuple(sensitivity),
                )
            )

    episodes.sort(
        key=lambda row: (row.touch_at, row.zone_id, row.touch_ordinal)
    )
    return tuple(episodes)


def _summary(
    rows: Sequence[TimeframeEpisode],
    *,
    horizon_m15: int | None = None,
) -> dict[str, Any]:
    selected = list(rows)
    outcomes = []
    for row in selected:
        if horizon_m15 is None:
            outcomes.append(row.primary_outcome)
            continue
        match = next(
            (
                outcome
                for horizon, outcome in row.sensitivity
                if int(horizon) == int(horizon_m15)
            ),
            None,
        )
        if match is not None:
            outcomes.append(match)
    n = len(outcomes)
    if not n:
        return {
            "n": 0,
            "holds": 0,
            "breaks": 0,
            "stalls": 0,
            "precision_hold": None,
            "wilson_lower_95": None,
        }
    holds = sum(bool(outcome.label_hold) for outcome in outcomes)
    breaks = sum(
        str(outcome.status).startswith("BREAK") for outcome in outcomes
    )
    stalls = sum(outcome.status == "STALL" for outcome in outcomes)
    mfe = [float(outcome.max_favorable_excursion_atr) for outcome in outcomes]
    mae = [float(outcome.max_adverse_excursion_atr) for outcome in outcomes]
    bars_to_outcome = [
        int(outcome.bars_to_outcome)
        for outcome in outcomes
        if outcome.bars_to_outcome is not None
    ]
    return {
        "n": n,
        "holds": int(holds),
        "breaks": int(breaks),
        "stalls": int(stalls),
        "precision_hold": holds / n,
        "wilson_lower_95": wilson_lower_bound(holds, n),
        "mean_mfe_atr": float(np.mean(mfe)),
        "median_mfe_atr": float(median(mfe)),
        "mean_mae_atr": float(np.mean(mae)),
        "median_mae_atr": float(median(mae)),
        "median_bars_to_outcome": (
            None
            if not bars_to_outcome
            else float(median(bars_to_outcome))
        ),
    }


def _split_chronological(
    rows: Sequence[TimeframeEpisode],
) -> tuple[tuple[TimeframeEpisode, ...], tuple[TimeframeEpisode, ...]]:
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


def _group_key(
    row: TimeframeEpisode,
    fields: Sequence[str],
) -> tuple[str, ...]:
    return tuple(str(getattr(row, field)) for field in fields)


def _group_report(
    rows: Sequence[TimeframeEpisode],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[TimeframeEpisode]] = {}
    for row in rows:
        groups.setdefault(_group_key(row, fields), []).append(row)
    output = []
    for key, members in groups.items():
        output.append(
            {
                "dimensions": dict(zip(fields, key)),
                **_summary(members),
            }
        )
    output.sort(
        key=lambda item: (
            -int(item.get("n") or 0),
            -float(item.get("precision_hold") or 0.0),
        )
    )
    return output


def _timeframe_report(
    rows: Sequence[TimeframeEpisode],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for timeframe, primary_horizon in PRIMARY_HORIZON_M15.items():
        selected = [row for row in rows if row.timeframe == timeframe]
        sensitivity = {}
        for horizon in SENSITIVITY_HORIZONS_M15[timeframe]:
            sensitivity[str(horizon)] = {
                "horizon_m15": int(horizon),
                "horizon_hours": int(horizon) * 0.25,
                **_summary(selected, horizon_m15=int(horizon)),
            }
        output[timeframe] = {
            "primary_horizon_m15": int(primary_horizon),
            "primary_horizon_hours": int(primary_horizon) * 0.25,
            "primary": _summary(selected),
            "sensitivity": sensitivity,
        }
    return output


def _candidate_groups(
    holdout: Sequence[TimeframeEpisode],
) -> list[dict[str, Any]]:
    candidates = []
    for fields in PRE_REGISTERED_GROUPS:
        for item in _group_report(holdout, fields):
            n = int(item.get("n") or 0)
            precision = item.get("precision_hold")
            if (
                n >= MIN_HOLDOUT_GROUP_N
                and precision is not None
                and float(precision) >= CLAIM_PRECISION
            ):
                candidates.append(
                    {
                        "group_contract": list(fields),
                        **item,
                        "promotion_authority": False,
                        "interpretation": (
                            "EXPLORATORY_TIMEFRAME_AWARE_HOLDOUT_SUBSET"
                        ),
                    }
                )
    candidates.sort(
        key=lambda item: (
            -float(item.get("wilson_lower_95") or 0.0),
            -int(item.get("n") or 0),
        )
    )
    return candidates[:25]


def evaluate_timeframe_aware_research(
    bars: Sequence[Bar],
) -> dict[str, Any]:
    episodes = build_timeframe_dataset(bars)
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
            "primary_hold": (
                "0.50_ATR_FAVORABLE_EXCURSION_BEFORE_DISTAL_BREAK"
            ),
            "break": (
                "M15_CLOSE_BEYOND_DISTAL_BEFORE_PRIMARY_HOLD;"
                "BREAK_WINS_SAME_BAR"
            ),
            "primary_horizons_m15": PRIMARY_HORIZON_M15,
            "sensitivity_horizons_m15": SENSITIVITY_HORIZONS_M15,
            "same_touch_population_across_horizon_sensitivity": True,
            "historical_spread": "EXCLUDED",
        },
        "split": {
            "development": len(development),
            "holdout": len(holdout),
            "development_fraction": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
        },
        "primary_by_timeframe": _timeframe_report(episodes),
    }
    if not development or not holdout:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_TIMEFRAME_HOLDOUT",
            "development_by_timeframe": {},
            "holdout_by_timeframe": {},
            "holdout_groups": {},
            "candidate_80_precision_subsets": [],
        }

    holdout_groups = {
        "|".join(fields): _group_report(holdout, fields)
        for fields in PRE_REGISTERED_GROUPS
    }
    candidates = _candidate_groups(holdout)
    return base | {
        "decision": (
            "TIMEFRAME_AWARE_80_PRECISION_SUBSETS_FOUND_NOT_PROMOTED"
            if candidates
            else "NO_TIMEFRAME_AWARE_80_PERCENT_HOLDOUT_SUBSET"
        ),
        "development_by_timeframe": _timeframe_report(development),
        "holdout_by_timeframe": _timeframe_report(holdout),
        "holdout_groups": holdout_groups,
        "candidate_80_precision_subsets": candidates,
        "candidate_policy": {
            "minimum_holdout_n": MIN_HOLDOUT_GROUP_N,
            "minimum_raw_precision": CLAIM_PRECISION,
            "automatic_promotion": False,
            "note": (
                "Horizon sensitivity uses the same touch episodes. "
                "Candidate subsets remain research-only."
            ),
        },
    }

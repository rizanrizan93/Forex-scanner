from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Sequence

from .demo_xau_afic_path_shadow_observer import _resample_completed
from .demo_xau_supply_demand_atlas_v182 import (
    M30_SHADOW_RULE,
    _dedupe_zones,
    _detect_base_departure_zones,
)
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_m30_parent_zone_v273 import (
    _best_parent,
    _invalidated_at,
    _overlap_bucket,
    _scan_touch_indices,
)
from .research_xau_supply_demand_reaction_v183 import (
    DEVELOPMENT_FRACTION,
    _all_zones,
    _invalidated,
    evaluate_reaction_outcome,
)
from .xau_m30_deep_rejection_v277 import (
    DEEP_TOUCH_MIN_DEPTH,
    MIN_REJECTION_RETREAT,
    REJECTION_CONFIRM_MAX_DEPTH,
    _bar_close_depth,
    _bar_penetration_depth,
)

RESEARCH_VERSION = "XAU_M30_DEEP_REJECTION_CALIBRATION_V277"
ARTIFACT_CONTRACT = "XAU_M30_DEEP_REJECTION_CALIBRATION_V277_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

CONFIRM_SEARCH_HORIZON_M15 = 32
POST_CONFIRM_HORIZON_M15 = 16
REACTION_ATR = 0.50
PURGE_HOURS = 48
MIN_HOLDOUT_N = 30


@dataclass(frozen=True, slots=True)
class DeepRejectionEpisode:
    zone_id: str
    direction: str
    touch_at: datetime
    touch_ordinal: int
    overlap_ratio: float
    overlap_bucket: str
    parent_timeframe: str | None
    max_depth: float
    deep_touch: bool
    confirmation_at: datetime | None
    confirmation_depth: float | None
    confirmation_retreat: float | None
    confirmed: bool
    confirmation_entry: float | None
    confirmed_outcome: str
    confirmed_hold_050: bool
    confirmed_mfe_atr: float
    confirmed_mae_atr: float
    confirmed_bars_to_outcome: int | None
    near_edge_hold_050: bool
    near_edge_status: str


def _confirmed_outcome(
    rows: Sequence[Bar],
    *,
    start_index: int,
    direction: str,
    entry: float,
    distal: float,
    atr: float,
) -> dict[str, Any]:
    side = str(direction or "").upper()
    max_favorable = 0.0
    max_adverse = 0.0
    future = rows[
        start_index + 1 : start_index + 1 + POST_CONFIRM_HORIZON_M15
    ]
    for offset, row in enumerate(future, start=1):
        if side == "SHORT":
            invalid = float(row.close) > float(distal)
            favorable = max(0.0, float(entry) - float(row.low))
            adverse = max(0.0, float(row.high) - float(entry))
        else:
            invalid = float(row.close) < float(distal)
            favorable = max(0.0, float(row.high) - float(entry))
            adverse = max(0.0, float(entry) - float(row.low))
        max_adverse = max(max_adverse, adverse)
        if invalid:
            return {
                "status": "BREAK",
                "hold_050": False,
                "mfe_atr": max_favorable / atr,
                "mae_atr": max_adverse / atr,
                "bars_to_outcome": offset,
            }
        max_favorable = max(max_favorable, favorable)
        if max_favorable + 1e-12 >= REACTION_ATR * atr:
            return {
                "status": "HOLD",
                "hold_050": True,
                "mfe_atr": max_favorable / atr,
                "mae_atr": max_adverse / atr,
                "bars_to_outcome": offset,
            }
    if len(future) < POST_CONFIRM_HORIZON_M15:
        status = "PENDING"
    else:
        status = "STALL"
    return {
        "status": status,
        "hold_050": False,
        "mfe_atr": max_favorable / atr,
        "mae_atr": max_adverse / atr,
        "bars_to_outcome": (
            None if status == "PENDING" else POST_CONFIRM_HORIZON_M15
        ),
    }


def _deep_rejection_confirmation(
    rows: Sequence[Bar],
    *,
    touch_index: int,
    direction: str,
    low: float,
    high: float,
) -> dict[str, Any]:
    max_depth = float("-inf")
    max_depth_at: datetime | None = None
    end = min(len(rows), touch_index + 1 + CONFIRM_SEARCH_HORIZON_M15)
    for index in range(touch_index, end):
        row = rows[index]
        penetration = _bar_penetration_depth(
            direction=direction,
            low=low,
            high=high,
            bar=row,
        )
        close_depth = _bar_close_depth(
            direction=direction,
            low=low,
            high=high,
            bar=row,
        )
        if penetration > max_depth:
            max_depth = penetration
            max_depth_at = ensure_utc(row.timestamp)

        if direction == "SHORT":
            invalid = float(row.close) > float(high)
        else:
            invalid = float(row.close) < float(low)
        if invalid:
            return {
                "max_depth": max_depth,
                "max_depth_at": max_depth_at,
                "deep_touch": max_depth >= DEEP_TOUCH_MIN_DEPTH,
                "confirmed": False,
                "invalidated_before_confirm": True,
                "confirmation_index": None,
                "confirmation_at": None,
                "confirmation_depth": None,
                "confirmation_retreat": None,
            }

        retreat = max_depth - close_depth
        if (
            max_depth >= DEEP_TOUCH_MIN_DEPTH
            and close_depth <= REJECTION_CONFIRM_MAX_DEPTH
            and retreat >= MIN_REJECTION_RETREAT
        ):
            return {
                "max_depth": max_depth,
                "max_depth_at": max_depth_at,
                "deep_touch": True,
                "confirmed": True,
                "invalidated_before_confirm": False,
                "confirmation_index": index,
                "confirmation_at": ensure_utc(row.timestamp),
                "confirmation_depth": close_depth,
                "confirmation_retreat": retreat,
            }

    return {
        "max_depth": max_depth if max_depth != float("-inf") else 0.0,
        "max_depth_at": max_depth_at,
        "deep_touch": max_depth >= DEEP_TOUCH_MIN_DEPTH,
        "confirmed": False,
        "invalidated_before_confirm": False,
        "confirmation_index": None,
        "confirmation_at": None,
        "confirmation_depth": None,
        "confirmation_retreat": None,
    }


def build_deep_rejection_dataset(
    bars: Sequence[Bar],
) -> tuple[DeepRejectionEpisode, ...]:
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

    output: list[DeepRejectionEpisode] = []
    for zone in m30_zones:
        for ordinal, touch_index in _scan_touch_indices(
            rows,
            row_times,
            zone=zone,
        ):
            if touch_index + CONFIRM_SEARCH_HORIZON_M15 >= len(rows):
                continue
            touch_at = ensure_utc(rows[touch_index].timestamp)
            overlap, parent = _best_parent(
                zone=zone,
                touch_at=touch_at,
                canonical=canonical,
                invalidated_by_id=invalidated_by_id,
            )
            deep = _deep_rejection_confirmation(
                rows,
                touch_index=touch_index,
                direction=zone.direction,
                low=float(zone.low),
                high=float(zone.high),
            )
            near = evaluate_reaction_outcome(
                rows,
                touch_index=touch_index,
                zone=zone,
                horizon_m15=CONFIRM_SEARCH_HORIZON_M15,
                primary_reaction_atr=REACTION_ATR,
            )
            confirm_index = deep.get("confirmation_index")
            confirmed = bool(deep.get("confirmed"))
            if confirmed and confirm_index is not None:
                entry = float(rows[int(confirm_index)].close)
                post = _confirmed_outcome(
                    rows,
                    start_index=int(confirm_index),
                    direction=zone.direction,
                    entry=entry,
                    distal=float(zone.distal),
                    atr=float(zone.atr_points),
                )
            else:
                entry = None
                post = {
                    "status": "NOT_CONFIRMED",
                    "hold_050": False,
                    "mfe_atr": 0.0,
                    "mae_atr": 0.0,
                    "bars_to_outcome": None,
                }
            if post["status"] == "PENDING":
                continue
            output.append(
                DeepRejectionEpisode(
                    zone_id=zone.zone_id,
                    direction=zone.direction,
                    touch_at=touch_at,
                    touch_ordinal=int(ordinal),
                    overlap_ratio=float(overlap),
                    overlap_bucket=_overlap_bucket(overlap),
                    parent_timeframe=None if parent is None else parent.timeframe,
                    max_depth=float(deep.get("max_depth") or 0.0),
                    deep_touch=bool(deep.get("deep_touch")),
                    confirmation_at=deep.get("confirmation_at"),
                    confirmation_depth=deep.get("confirmation_depth"),
                    confirmation_retreat=deep.get("confirmation_retreat"),
                    confirmed=confirmed,
                    confirmation_entry=entry,
                    confirmed_outcome=str(post["status"]),
                    confirmed_hold_050=bool(post["hold_050"]),
                    confirmed_mfe_atr=float(post["mfe_atr"]),
                    confirmed_mae_atr=float(post["mae_atr"]),
                    confirmed_bars_to_outcome=post["bars_to_outcome"],
                    near_edge_hold_050=bool(near.label_hold),
                    near_edge_status=str(near.status),
                )
            )
    output.sort(key=lambda row: (row.touch_at, row.zone_id, row.touch_ordinal))
    return tuple(output)


def _summary(rows: Sequence[DeepRejectionEpisode]) -> dict[str, Any]:
    selected = tuple(rows)
    n = len(selected)
    if not n:
        return {
            "n": 0,
            "deep_touch_rate": None,
            "deep_rejection_confirm_rate": None,
            "deep_rejection_hold_050_rate": None,
            "near_edge_hold_050_same_confirmed_population": None,
        }
    deep = [row for row in selected if row.deep_touch]
    confirmed = [row for row in selected if row.confirmed]
    confirmed_success = [row for row in confirmed if row.confirmed_hold_050]
    near_same = [row for row in confirmed if row.near_edge_hold_050]
    return {
        "n": n,
        "deep_touch_n": len(deep),
        "deep_touch_rate": len(deep) / n,
        "deep_rejection_confirm_n": len(confirmed),
        "deep_rejection_confirm_rate": (
            None if not deep else len(confirmed) / len(deep)
        ),
        "deep_rejection_hold_050_n": len(confirmed_success),
        "deep_rejection_hold_050_rate": (
            None if not confirmed else len(confirmed_success) / len(confirmed)
        ),
        "near_edge_hold_050_same_confirmed_population": (
            None if not confirmed else len(near_same) / len(confirmed)
        ),
        "confirmation_minus_near_edge_delta": (
            None
            if not confirmed
            else (
                len(confirmed_success) / len(confirmed)
                - len(near_same) / len(confirmed)
            )
        ),
        "median_max_depth_confirmed": (
            None
            if not confirmed
            else float(median(row.max_depth for row in confirmed))
        ),
        "median_confirmation_depth": (
            None
            if not confirmed
            else float(
                median(
                    float(row.confirmation_depth)
                    for row in confirmed
                    if row.confirmation_depth is not None
                )
            )
        ),
        "median_confirmation_retreat": (
            None
            if not confirmed
            else float(
                median(
                    float(row.confirmation_retreat)
                    for row in confirmed
                    if row.confirmation_retreat is not None
                )
            )
        ),
        "median_confirmed_mfe_atr": (
            None
            if not confirmed
            else float(median(row.confirmed_mfe_atr for row in confirmed))
        ),
        "median_confirmed_mae_atr": (
            None
            if not confirmed
            else float(median(row.confirmed_mae_atr for row in confirmed))
        ),
    }


def _group_report(
    rows: Sequence[DeepRejectionEpisode],
    field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[DeepRejectionEpisode]] = {}
    for row in rows:
        groups.setdefault(str(getattr(row, field)), []).append(row)
    result = [
        {"group": key, **_summary(members)}
        for key, members in groups.items()
    ]
    result.sort(key=lambda item: -int(item.get("n") or 0))
    return result


def _split(
    rows: Sequence[DeepRejectionEpisode],
) -> tuple[tuple[DeepRejectionEpisode, ...], tuple[DeepRejectionEpisode, ...]]:
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


def evaluate_deep_rejection_research(
    bars: Sequence[Bar],
) -> dict[str, Any]:
    episodes = build_deep_rejection_dataset(bars)
    development, holdout = _split(episodes)
    base = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "episodes": len(episodes),
        "thresholds": {
            "deep_touch_min_depth": DEEP_TOUCH_MIN_DEPTH,
            "confirmation_max_depth": REJECTION_CONFIRM_MAX_DEPTH,
            "minimum_retreat": MIN_REJECTION_RETREAT,
            "reaction_atr": REACTION_ATR,
            "confirmation_search_horizon_m15": CONFIRM_SEARCH_HORIZON_M15,
            "post_confirmation_horizon_m15": POST_CONFIRM_HORIZON_M15,
        },
        "overall": _summary(episodes),
        "by_overlap": _group_report(episodes, "overlap_bucket"),
        "by_direction": _group_report(episodes, "direction"),
        "split": {
            "development": len(development),
            "holdout": len(holdout),
            "purge_hours": PURGE_HOURS,
        },
        "interpretation": (
            "Near-edge is the parent-zone first-touch baseline. Deep-rejection entry "
            "is only measured after >=60% penetration followed by a >=20%-width retreat "
            "and a close back to <=55% depth. Neither result grants execution authority."
        ),
    }
    if not development or not holdout:
        return base | {
            "decision": "DATA_INSUFFICIENT_FOR_V277_HOLDOUT",
            "development": {},
            "holdout": {},
            "holdout_by_overlap": [],
            "promotion_authority": False,
        }
    holdout_summary = _summary(holdout)
    confirmed_n = int(holdout_summary.get("deep_rejection_confirm_n") or 0)
    return base | {
        "decision": (
            "V277_DEEP_REJECTION_EVIDENCE_READY_SHADOW_ONLY"
            if confirmed_n >= MIN_HOLDOUT_N
            else "V277_MORE_DEEP_REJECTION_EVIDENCE_REQUIRED"
        ),
        "development": _summary(development),
        "holdout": holdout_summary,
        "holdout_by_overlap": _group_report(holdout, "overlap_bucket"),
        "minimum_holdout_confirmed_n": MIN_HOLDOUT_N,
        "promotion_authority": False,
    }

from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

from .xau_rizan_micro_entry_dual_cycle_v321 import (
    build_dual_cycle_micro_refinement,
)

CONTRACT = "RIZAN_STYLE_MICRO_HANDOFF_CONFLUENCE_V322"
DISPLAY_NAME = "RIZAN STYLE MICRO HANDOFF CONFLUENCE"
POLICY_EFFECT = "RESEARCH_FORECAST_ONLY"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False

SOURCE_RETEST_MAX_DISTANCE_ATR = 0.75


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone_distance_atr(
    *,
    price: float | None,
    zone: dict[str, Any],
) -> float | None:
    if price is None or not zone:
        return None
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    atr = _f(zone.get("atr_points"))
    if low is None or high is None or atr is None or atr <= 0:
        return None
    if low <= price <= high:
        return 0.0
    distance = low - price if price < low else price - high
    return max(0.0, float(distance)) / float(atr)


def _touched(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    return bool(
        int(lifecycle.get("touch_count") or 0) > 0
        or lifecycle.get("first_touch_at")
        or lifecycle.get("last_touch_at")
    )


def _micro_context(atlas: dict[str, Any]) -> dict[str, Any]:
    projection = dict(atlas.get("m5_path_projection") or {})
    current_leg = dict(projection.get("current_leg") or {})
    micro = dict(current_leg.get("micro_refinement") or {})
    reuse = dict(current_leg.get("zone_reuse_v200") or {})
    candidate = dict(reuse.get("active_candidate_micro_pocket") or {})
    refined = dict(reuse.get("active_refined_micro_pocket") or {})
    return {
        "state": str(micro.get("state") or "WAIT"),
        "direction": str(micro.get("direction") or "").upper() or None,
        "sweep": dict(micro.get("sweep") or {}),
        "reclaim_at": micro.get("reclaim_at"),
        "mss_level": _f(micro.get("mss_level")),
        "mss_confirmed": bool(micro.get("mss_confirmed")),
        "mss_at": micro.get("mss_at"),
        "displacement_at": micro.get("displacement_at"),
        "candidate_micro_pocket": candidate,
        "refined_micro_pocket": refined,
        "reuse_state": reuse.get("state"),
        "reuse_priority": reuse.get("priority"),
        "fresh_micro_confirmed": bool(reuse.get("fresh_micro_confirmed")),
    }


def build_micro_handoff_confluence(
    *,
    atlas_evaluation: dict[str, Any],
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_h1: Iterable[Any],
    price_now: float | None = None,
) -> dict[str, Any]:
    atlas = dict(atlas_evaluation or {})
    base = build_dual_cycle_micro_refinement(
        atlas_evaluation=atlas,
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=price_now,
    )
    current = _f(base.get("price_now"))
    active = dict(base.get("active_source") or {})
    nxt = dict(base.get("next_opposing") or {})
    source_zone = dict(active.get("zone") or {})
    next_zone = dict(nxt.get("zone") or {})
    source_relation = str(active.get("price_relation") or "UNKNOWN")
    next_relation = str(nxt.get("price_relation") or "UNKNOWN")
    source_distance_atr = _zone_distance_atr(price=current, zone=source_zone)
    next_distance_atr = _zone_distance_atr(price=current, zone=next_zone)

    active_m5 = dict(active.get("m5") or {})
    next_m5 = dict(nxt.get("m5") or {})

    source_no_chase = bool(
        source_relation == "REACTION_SIDE"
        and source_distance_atr is not None
        and source_distance_atr > SOURCE_RETEST_MAX_DISTANCE_ATR
    )

    if next_zone and next_relation == "INSIDE":
        preferred = "NEXT_OPPOSING_M5"
        handoff = "NEXT_OPPOSING_ZONE_ENTERED"
    elif source_zone and source_relation == "INSIDE":
        preferred = "ACTIVE_SOURCE_M5"
        handoff = "ACTIVE_SOURCE_ZONE_MICRO_WATCH"
    elif (
        source_zone
        and _touched(source_zone)
        and source_relation == "REACTION_SIDE"
        and not source_no_chase
    ):
        preferred = "ACTIVE_SOURCE_M5"
        handoff = "POST_SOURCE_RETEST_WINDOW"
    elif next_zone:
        preferred = "NEXT_OPPOSING_M5"
        handoff = (
            "SOURCE_MOVE_IN_FLIGHT_NO_CHASE_PREPARE_NEXT"
            if source_no_chase
            else "TRAVEL_TO_NEXT_OPPOSING_ZONE"
        )
    elif source_zone:
        preferred = "ACTIVE_SOURCE_M5"
        handoff = "SOURCE_ONLY"
    else:
        preferred = "NONE"
        handoff = "NO_STRUCTURAL_ZONE"

    primary = (
        active_m5
        if preferred == "ACTIVE_SOURCE_M5"
        else next_m5
        if preferred == "NEXT_OPPOSING_M5"
        else {}
    )

    micro_context = _micro_context(atlas)
    active["micro_context"] = micro_context
    active["distance_atr"] = source_distance_atr
    active["no_chase"] = source_no_chase
    nxt["distance_atr"] = next_distance_atr

    output = dict(base)
    output.update(
        {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": handoff,
            "primary_setup_role": preferred,
            "primary": primary,
            "active_source": active,
            "next_opposing": nxt,
            "direction": primary.get("direction"),
            "phase": primary.get("phase"),
            "selected_timeframe": primary.get("selected_timeframe"),
            "decision_zone": primary.get("decision_zone"),
            "anchor": primary.get("anchor"),
            "delta": primary.get("delta"),
            "levels": primary.get("levels"),
            "entries": primary.get("entries"),
            "targets": primary.get("targets"),
            "reclaim_confirmed": primary.get("reclaim_confirmed"),
            "confidence": primary.get("confidence"),
            "nearest_opposing_zone": primary.get("nearest_opposing_zone"),
            "structural_conflict_price": primary.get("structural_conflict_price"),
            "source_retest_max_distance_atr": SOURCE_RETEST_MAX_DISTANCE_ATR,
            "source_no_chase": source_no_chase,
            "interpretation": (
                "V322 keeps the currently active source and the next opposing reversal "
                "as separate A/X/Y cycles, but adds a no-chase handoff. The active source "
                "is primary only while price is inside it or remains within 0.75 source ATR "
                "after a reaction. Once price travels farther, the source remains visible "
                "for context but the next opposing zone becomes the preparation focus. "
                "V182 M5 sweep/MSS/reclaim context is attached to the active-source panel "
                "as confluence, not as execution authority."
            ),
            "policy_effect": POLICY_EFFECT,
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        }
    )
    return output

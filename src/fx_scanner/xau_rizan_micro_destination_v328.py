from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

from .xau_rizan_micro_entry_refinement_v320 import build_micro_entry_refinement
from .xau_rizan_micro_handoff_v322 import (
    SOURCE_RETEST_MAX_DISTANCE_ATR,
    build_micro_handoff_confluence,
)

CONTRACT = "RIZAN_STYLE_OPPOSING_ZONE_CASCADE_V328"
DISPLAY_NAME = "RIZAN STYLE OPPOSING ZONE CASCADE"
POLICY_EFFECT = "RESEARCH_FORECAST_ONLY"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _valid_zone(zone: dict[str, Any]) -> bool:
    if not zone:
        return False
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "").upper()
    lifecycle = dict(zone.get("lifecycle") or {})
    status = str(zone.get("status") or "").upper()
    return bool(
        low is not None
        and high is not None
        and high > low
        and direction in {"LONG", "SHORT"}
        and lifecycle.get("active", True) is not False
        and "BROKEN" not in status
        and "INVALID" not in status
    )


def _relation(price: float | None, zone: dict[str, Any]) -> str:
    if price is None or not _valid_zone(zone):
        return "UNKNOWN"
    low = float(zone["low"])
    high = float(zone["high"])
    direction = str(zone.get("direction") or "").upper()
    if low <= price <= high:
        return "INSIDE"
    if direction == "LONG":
        return "REACTION_SIDE" if price > high else "BREAK_SIDE"
    return "REACTION_SIDE" if price < low else "BREAK_SIDE"


def _touched(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    return bool(
        int(lifecycle.get("touch_count") or 0) > 0
        or lifecycle.get("first_touch_at")
        or lifecycle.get("last_touch_at")
    )


def _zone_key(zone: dict[str, Any]) -> str:
    zone_id = str(zone.get("zone_id") or "")
    if zone_id:
        return zone_id
    return "|".join(
        [
            str(zone.get("timeframe") or ""),
            str(zone.get("direction") or ""),
            str(zone.get("low") or ""),
            str(zone.get("high") or ""),
        ]
    )


def _candidate_zones(atlas: dict[str, Any]) -> list[dict[str, Any]]:
    path_map = dict(atlas.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    raw = [
        active_path.get("primary_opposing_zone"),
        active_path.get("terminal_target_zone"),
        *list(active_path.get("destination_stack") or []),
        *list(active_path.get("secondary_opposing_zones") or []),
    ]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        zone = dict(item or {})
        if not zone:
            continue
        key = _zone_key(zone)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(zone)
    return output


def _skip_summary(
    zone: dict[str, Any],
    *,
    relation: str,
    reason: str,
) -> dict[str, Any]:
    lifecycle = dict(zone.get("lifecycle") or {})
    return {
        "zone_id": zone.get("zone_id"),
        "timeframe": zone.get("timeframe"),
        "direction": zone.get("direction"),
        "low": _f(zone.get("low")),
        "high": _f(zone.get("high")),
        "proximal": _f(zone.get("proximal")),
        "distal": _f(zone.get("distal")),
        "relation": relation,
        "reason": reason,
        "touch_count": int(lifecycle.get("touch_count") or 0),
        "mitigation_depth": _f(lifecycle.get("mitigation_depth")),
        "invalidated_at": lifecycle.get("invalidated_at"),
        "freshness": lifecycle.get("freshness"),
    }


def _select_opposing_zone(
    *,
    atlas: dict[str, Any],
    current: float | None,
    source_zone: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], int | None]:
    source_direction = str(source_zone.get("direction") or "").upper()
    expected = (
        "LONG"
        if source_direction == "SHORT"
        else "SHORT"
        if source_direction == "LONG"
        else None
    )
    skipped: list[dict[str, Any]] = []
    selected_rank: int | None = None

    for rank, zone in enumerate(_candidate_zones(atlas), start=1):
        direction = str(zone.get("direction") or "").upper()
        if expected and direction != expected:
            skipped.append(
                _skip_summary(
                    zone,
                    relation="DIRECTION_MISMATCH",
                    reason="NOT_OPPOSING_SOURCE_DIRECTION",
                )
            )
            continue
        if not _valid_zone(zone):
            skipped.append(
                _skip_summary(
                    zone,
                    relation="INVALID",
                    reason="ZONE_INACTIVE_BROKEN_OR_INVALID",
                )
            )
            continue

        relation = _relation(current, zone)
        if relation == "BREAK_SIDE":
            skipped.append(
                _skip_summary(
                    zone,
                    relation=relation,
                    reason="LIVE_PRICE_BEYOND_DISTAL",
                )
            )
            continue

        selected_rank = rank
        return zone, skipped, selected_rank

    return {}, skipped, selected_rank


def _setup_for_zone(
    *,
    atlas: dict[str, Any],
    zone: dict[str, Any],
    role: str,
    timeframe: str,
    bars_m5: tuple[Any, ...],
    bars_m15: tuple[Any, ...],
    bars_h1: tuple[Any, ...],
    price_now: float | None,
) -> dict[str, Any]:
    if not zone:
        return {
            "state": "NO_ZONE",
            "setup_role": role,
            "selected_timeframe": timeframe,
            "execution_authority": False,
            "execution_influence": False,
        }
    return build_micro_entry_refinement(
        atlas_evaluation=atlas,
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=price_now,
        zone_override=zone,
        timeframe_preference=timeframe,
        setup_role=role,
    )


def build_opposing_zone_cascade(
    *,
    atlas_evaluation: dict[str, Any],
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_h1: Iterable[Any],
    price_now: float | None = None,
) -> dict[str, Any]:
    atlas = dict(atlas_evaluation or {})
    m5 = tuple(bars_m5)
    m15 = tuple(bars_m15)
    h1 = tuple(bars_h1)

    base = build_micro_handoff_confluence(
        atlas_evaluation=atlas,
        bars_m5=m5,
        bars_m15=m15,
        bars_h1=h1,
        price_now=price_now,
    )

    current = _f(base.get("price_now"))
    active = dict(base.get("active_source") or {})
    source_zone = dict(active.get("zone") or {})
    source_relation = str(active.get("price_relation") or "UNKNOWN")
    source_no_chase = bool(base.get("source_no_chase"))
    active_m5 = dict(active.get("m5") or {})

    selected_zone, skipped, selected_rank = _select_opposing_zone(
        atlas=atlas,
        current=current,
        source_zone=source_zone,
    )
    selected_relation = _relation(current, selected_zone)

    previous_next = dict(base.get("next_opposing") or {})
    previous_zone = dict(previous_next.get("zone") or {})
    previous_id = _zone_key(previous_zone)
    selected_id = _zone_key(selected_zone)
    cascaded = bool(
        selected_zone
        and previous_zone
        and selected_id
        and previous_id
        and selected_id != previous_id
    )

    if selected_zone and selected_id == previous_id:
        next_m5 = dict(previous_next.get("m5") or {})
        next_h1 = dict(previous_next.get("h1") or {})
    else:
        next_m5 = _setup_for_zone(
            atlas=atlas,
            zone=selected_zone,
            role="CASCADED_NEXT_OPPOSING_REVERSAL",
            timeframe="M5",
            bars_m5=m5,
            bars_m15=m15,
            bars_h1=h1,
            price_now=current,
        )
        next_h1 = _setup_for_zone(
            atlas=atlas,
            zone=selected_zone,
            role="CASCADED_NEXT_OPPOSING_REVERSAL",
            timeframe="H1",
            bars_m5=m5,
            bars_m15=m15,
            bars_h1=h1,
            price_now=current,
        )

    next_opposing = {
        "zone": selected_zone,
        "price_relation": selected_relation if selected_zone else "NO_SAFE_ZONE",
        "m5": next_m5,
        "h1": next_h1,
        "selected_rank": selected_rank,
        "cascaded": cascaded,
    }

    if selected_zone and selected_relation == "INSIDE":
        preferred = "NEXT_OPPOSING_M5"
        handoff = (
            "CASCADED_OPPOSING_ZONE_ENTERED"
            if skipped or cascaded
            else "NEXT_OPPOSING_ZONE_ENTERED"
        )
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
    elif selected_zone:
        preferred = "NEXT_OPPOSING_M5"
        if skipped or cascaded:
            handoff = "CASCADE_TO_DEEPER_OPPOSING_ZONE"
        elif source_no_chase:
            handoff = "SOURCE_MOVE_IN_FLIGHT_NO_CHASE_PREPARE_NEXT"
        else:
            handoff = "TRAVEL_TO_NEXT_OPPOSING_ZONE"
    elif skipped:
        preferred = "NONE"
        handoff = "WAIT_STRUCTURAL_REMAP_AFTER_OPPOSING_BREACH"
    elif source_zone and not source_no_chase and source_relation != "BREAK_SIDE":
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

    possible_sweep = [
        row
        for row in skipped
        if row.get("reason") == "LIVE_PRICE_BEYOND_DISTAL"
        and not row.get("invalidated_at")
    ]
    liquidity_context = {
        "state": (
            "POSSIBLE_LIQUIDITY_SWEEP_OR_ACCEPTANCE"
            if possible_sweep
            else "CLEAR"
        ),
        "upstream_breached_zones": possible_sweep,
        "requires_reclaim_or_structural_remap": bool(possible_sweep),
        "note": (
            "A live price beyond distal is not treated as a clean reversal entry. "
            "It may be a liquidity sweep or acceptance through the zone; the scanner "
            "cascades to the next deeper structural zone until reclaim/remap resolves it."
            if possible_sweep
            else "No upstream opposing-zone distal breach is active."
        ),
    }

    output = dict(base)
    output.update(
        {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": handoff,
            "primary_setup_role": preferred,
            "primary": primary,
            "next_opposing": next_opposing,
            "destination_cascade": {
                "cascaded": cascaded,
                "selected_rank": selected_rank,
                "selected_zone_id": selected_zone.get("zone_id") if selected_zone else None,
                "selected_relation": (
                    selected_relation if selected_zone else "NO_SAFE_ZONE"
                ),
                "skipped_count": len(skipped),
                "skipped_zones": skipped,
            },
            "liquidity_sweep_context": liquidity_context,
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
                "V328 prevents a stale opposing zone from remaining the primary entry "
                "after live price has already crossed its distal boundary. Such a zone "
                "is retained as possible liquidity-sweep/acceptance context, while the "
                "micro ladder cascades to the next deeper still-valid opposing zone. "
                "If no safe destination remains, the scanner waits for a structural remap "
                "instead of publishing a stale A/X/Y reversal ladder."
            ),
            "policy_effect": POLICY_EFFECT,
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        }
    )
    return output

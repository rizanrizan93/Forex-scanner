from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

from .xau_rizan_micro_entry_refinement_v320 import (
    POLICY_EFFECT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    build_micro_entry_refinement,
)

CONTRACT = "RIZAN_STYLE_MICRO_ENTRY_DUAL_CYCLE_V321"
DISPLAY_NAME = "RIZAN STYLE MICRO ENTRY DUAL CYCLE"
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


def _source_zone(atlas: dict[str, Any]) -> dict[str, Any]:
    path_map = dict(atlas.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    zone = dict(active_path.get("source_zone") or {})
    return zone if _valid_zone(zone) else {}


def _next_zone(atlas: dict[str, Any]) -> dict[str, Any]:
    path_map = dict(atlas.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    for raw in (
        active_path.get("primary_opposing_zone"),
        active_path.get("terminal_target_zone"),
        *list(active_path.get("destination_stack") or []),
    ):
        zone = dict(raw or {})
        if _valid_zone(zone):
            return zone
    return {}


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


def _recently_touched(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    touch_count = int(lifecycle.get("touch_count") or 0)
    return bool(
        touch_count > 0
        or lifecycle.get("first_touch_at")
        or lifecycle.get("last_touch_at")
    )


def _setup(
    *,
    atlas: dict[str, Any],
    zone: dict[str, Any],
    role: str,
    timeframe: str,
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_h1: Iterable[Any],
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


def _prefer_primary(
    *,
    source_zone: dict[str, Any],
    next_zone: dict[str, Any],
    price_now: float | None,
) -> str:
    source_relation = _relation(price_now, source_zone)
    if source_zone and source_relation == "INSIDE":
        return "ACTIVE_SOURCE_M5"
    if source_zone and _recently_touched(source_zone) and source_relation != "BREAK_SIDE":
        return "ACTIVE_SOURCE_M5"
    if next_zone:
        return "NEXT_OPPOSING_M5"
    if source_zone:
        return "ACTIVE_SOURCE_M5"
    return "NONE"


def build_dual_cycle_micro_refinement(
    *,
    atlas_evaluation: dict[str, Any],
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_h1: Iterable[Any],
    price_now: float | None = None,
) -> dict[str, Any]:
    atlas = dict(atlas_evaluation or {})
    source = _source_zone(atlas)
    next_zone = _next_zone(atlas)
    current = _f(price_now)

    active_m5 = _setup(
        atlas=atlas,
        zone=source,
        role="ACTIVE_SOURCE_REVERSAL",
        timeframe="M5",
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=current,
    )
    active_h1 = _setup(
        atlas=atlas,
        zone=source,
        role="ACTIVE_SOURCE_REVERSAL",
        timeframe="H1",
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=current,
    )
    next_m5 = _setup(
        atlas=atlas,
        zone=next_zone,
        role="NEXT_OPPOSING_REVERSAL",
        timeframe="M5",
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=current,
    )
    next_h1 = _setup(
        atlas=atlas,
        zone=next_zone,
        role="NEXT_OPPOSING_REVERSAL",
        timeframe="H1",
        bars_m5=bars_m5,
        bars_m15=bars_m15,
        bars_h1=bars_h1,
        price_now=current,
    )

    preferred = _prefer_primary(
        source_zone=source,
        next_zone=next_zone,
        price_now=current,
    )
    primary = {
        "ACTIVE_SOURCE_M5": active_m5,
        "NEXT_OPPOSING_M5": next_m5,
    }.get(preferred, {})
    if not primary:
        primary = active_m5 if active_m5.get("state") != "NO_ZONE" else next_m5

    source_relation = _relation(current, source)
    next_relation = _relation(current, next_zone)
    handoff_state = "NO_STRUCTURAL_ZONE"
    if source and source_relation == "INSIDE":
        handoff_state = "ACTIVE_SOURCE_ZONE_MICRO_WATCH"
    elif source and _recently_touched(source) and source_relation == "REACTION_SIDE":
        handoff_state = "POST_SOURCE_REACTION_MONITOR"
    elif next_zone and next_relation == "INSIDE":
        handoff_state = "NEXT_OPPOSING_ZONE_ENTERED"
    elif next_zone:
        handoff_state = "TRAVEL_TO_NEXT_OPPOSING_ZONE"
    elif source:
        handoff_state = "SOURCE_ONLY"

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": handoff_state,
        "price_now": current,
        "primary_setup_role": preferred,
        "primary": primary,
        "active_source": {
            "zone": source,
            "price_relation": source_relation,
            "m5": active_m5,
            "h1": active_h1,
        },
        "next_opposing": {
            "zone": next_zone,
            "price_relation": next_relation,
            "m5": next_m5,
            "h1": next_h1,
        },
        # Flat compatibility fields for the dashboard/analytics path.
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
        "interpretation": (
            "V321 separates the micro cycle at the currently active structural source "
            "from the pre-map of the next opposing reversal zone. When price is inside "
            "or has just reacted from the active source, that cycle is primary. The next "
            "opposing cycle remains visible as preparation only. Each cycle exposes both "
            "M5 fast refinement and H1 swing-scale A/X/Y geometry. The original reference "
            "indicator formula remains unknown and this module is research-only."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

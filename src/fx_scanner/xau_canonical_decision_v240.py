from __future__ import annotations

from math import isfinite
from typing import Any

from .demo_xau_v229_ladder_plan import build_parent_ladder_plan


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _active_zone(zone: dict[str, Any]) -> bool:
    if not zone:
        return False
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle and not bool(lifecycle.get("active", True)):
        return False
    state = str(zone.get("status") or "").upper()
    return "INVALID" not in state and "BROKEN" not in state


def _zone_text(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        "zone_id": str(zone.get("zone_id") or ""),
        "timeframe": str(zone.get("timeframe") or "").upper(),
        "direction": str(zone.get("direction") or "").upper(),
        "low": _f(zone.get("low")),
        "high": _f(zone.get("high")),
        "proximal": _f(zone.get("proximal")),
        "distal": _f(zone.get("distal")),
        "freshness": str(dict(zone.get("lifecycle") or {}).get("freshness") or ""),
        "touch_count": dict(zone.get("lifecycle") or {}).get("touch_count"),
        "research_score": _f(zone.get("research_score")),
    }


def _structural_zone_candidates(
    atlas_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return every currently mapped structural zone V240 is allowed to inspect.

    V182 can promote a newly formed H1/M15 source into path_map.active_path or
    m5_path_projection before that source is represented in the legacy flat zones
    collection. Restricting V240 to zones therefore leaves the dashboard pinned
    to an older V226 H4 parent.

    This union is read-only. Discovering a closer local source never grants
    execution authority; it only allows the existing LOCAL_REMAP fail-closed
    path to see the structure and suppress obsolete V226 entry geometry.
    """
    collected: list[dict[str, Any]] = [
        dict(item or {}) for item in list(atlas_evaluation.get("zones") or [])
    ]

    path_map = dict(atlas_evaluation.get("path_map") or {})
    for path_name in ("active_path", "demand_to_supply", "supply_to_demand"):
        path = dict(path_map.get(path_name) or {})
        for key in ("source_zone", "primary_opposing_zone", "terminal_target_zone"):
            zone = dict(path.get(key) or {})
            if zone:
                collected.append(zone)
        for raw in list(path.get("destination_stack") or []):
            zone = dict(raw or {})
            if zone:
                collected.append(zone)

    projections = [
        dict(atlas_evaluation.get("m5_path_projection") or {}),
        dict(path_map.get("m5_path_projection") or {}),
    ]
    for projection in projections:
        for leg_name in ("current_leg", "next_leg"):
            leg = dict(projection.get(leg_name) or {})
            zone = dict(leg.get("source_zone") or {})
            if zone:
                collected.append(zone)
            terminal = dict(leg.get("terminal_target_zone") or {})
            if terminal:
                collected.append(terminal)

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for zone in collected:
        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        zone_id = str(zone.get("zone_id") or "")
        key = (
            "ID",
            zone_id,
        ) if zone_id else (
            "GEOMETRY",
            str(zone.get("timeframe") or "").upper(),
            str(zone.get("direction") or "").upper(),
            None if low is None else round(low, 4),
            None if high is None else round(high, 4),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(zone)
    return unique


def _nearest_active_zone(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
    price: float | None,
) -> dict[str, Any]:
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for raw in _structural_zone_candidates(atlas_evaluation):
        zone = dict(raw or {})
        if str(zone.get("direction") or "").upper() != direction:
            continue
        if not _active_zone(zone):
            continue
        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        if low is None or high is None or high <= low:
            continue
        if price is None:
            distance = abs(_f(zone.get("distance_points")) or 1e9)
        elif price < low:
            distance = low - price
        elif price > high:
            distance = price - high
        else:
            distance = 0.0
        score = _f(zone.get("research_score")) or 0.0
        candidates.append((distance, -score, zone))
    if not candidates:
        return {}
    candidates.sort(key=lambda row: (row[0], row[1]))
    return _zone_text(candidates[0][2])


def _local_zone_supersedes_candidate(
    *,
    direction: str,
    price: float | None,
    candidate: dict[str, Any],
    local_zone: dict[str, Any],
) -> bool:
    """True when an active same-direction local zone sits between price and V226.

    V226 is intentionally H4-parent hierarchical. That can leave a valid but very
    distant nested locator selected while a newer H1/M15 structural source has
    formed closer to price. The local source may come from the flat atlas zone list
    or directly from V182 active/current path. The dashboard must not label the
    distant locator as the primary entry in that case. This helper is
    display/fail-closed only; it does not grant execution authority to the local
    structure.
    """
    px = _f(price)
    c_low = _f(candidate.get("entry_low"))
    c_high = _f(candidate.get("entry_high"))
    l_low = _f(local_zone.get("low"))
    l_high = _f(local_zone.get("high"))
    side = str(direction or "").upper()
    if None in {px, c_low, c_high, l_low, l_high}:
        return False
    assert px is not None and c_low is not None and c_high is not None
    assert l_low is not None and l_high is not None
    if side == "SHORT":
        return bool(px <= l_high < c_low)
    if side == "LONG":
        return bool(c_high < l_low <= px)
    return False


def _primary_reversal_watch(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
    price: float | None,
    zone_probabilities: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if direction not in {"LONG", "SHORT"}:
        return {}
    probability_by_id = {
        str(dict(row).get("zone_id") or ""): dict(row)
        for row in list(zone_probabilities or [])
        if dict(row).get("zone_id")
    }
    opposing = "SHORT" if direction == "LONG" else "LONG"
    ranked: list[tuple[float, float, dict[str, Any]]] = []
    for raw in list(atlas_evaluation.get("zones") or []):
        zone = dict(raw or {})
        if str(zone.get("direction") or "").upper() != opposing:
            continue
        if not _active_zone(zone):
            continue
        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        if low is None or high is None or high <= low:
            continue
        if price is not None:
            if direction == "LONG" and high <= price:
                continue
            if direction == "SHORT" and low >= price:
                continue
        evidence = dict(probability_by_id.get(str(zone.get("zone_id") or "")) or {})
        destination = dict(evidence.get("destination") or {})
        reaction = dict(evidence.get("reaction") or {})
        p_touch = _f(destination.get("p_touch"))
        p_hold = _f(reaction.get("p_hold_050"))
        if p_touch is None or p_hold is None:
            continue
        joint_score = max(0.0, min(1.0, p_touch)) * max(0.0, min(1.0, p_hold))
        if price is None:
            distance = abs(_f(zone.get("distance_points")) or 1e9)
        elif price < low:
            distance = low - price
        elif price > high:
            distance = price - high
        else:
            distance = 0.0
        result = {
            **_zone_text(zone),
            "p_touch": p_touch,
            "p_hold_050": p_hold,
            "p_break": _f(reaction.get("p_break")),
            "research_joint_score": joint_score,
            "confidence": str(reaction.get("confidence") or ""),
            "estimate_type": str(reaction.get("estimate_type") or ""),
            "not_calibrated_probability_claim": bool(
                reaction.get("not_calibrated_probability_claim", True)
            ),
            "distance_points": distance,
        }
        ranked.append((-joint_score, distance, result))
    if not ranked:
        return {}
    ranked.sort(key=lambda row: (row[0], row[1]))
    return ranked[0][2]


def _path_for_direction(
    atlas_evaluation: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    path_map = dict(atlas_evaluation.get("path_map") or {})
    return dict(
        path_map.get(
            "demand_to_supply" if direction == "LONG" else "supply_to_demand"
        )
        or {}
    )


def _collect_structural_targets(plan: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for child in list(plan.get("children") or []):
        for raw in list(dict(child).get("structural_targets") or []):
            row = dict(raw or {})
            price = _f(row.get("target_price"))
            if price is None:
                continue
            timeframe = str(row.get("timeframe") or "").upper()
            zone_id = str(row.get("zone_id") or "")
            key = (timeframe, zone_id, round(price, 4))
            if key in seen:
                continue
            seen.add(key)
            output.append(
                {
                    "target_price": price,
                    "timeframe": timeframe,
                    "zone_id": zone_id,
                    "role": str(row.get("role") or ""),
                    "zone_low": _f(row.get("zone_low")),
                    "zone_high": _f(row.get("zone_high")),
                    "rr": _f(row.get("rr")),
                }
            )
    direction = str(plan.get("direction") or "").upper()
    output.sort(
        key=lambda row: float(row["target_price"]),
        reverse=direction == "SHORT",
    )
    return output


def _saved_geometry_matches(
    saved_geometry: dict[str, Any],
    plan: dict[str, Any],
) -> bool:
    if not saved_geometry or not plan:
        return False
    if str(saved_geometry.get("direction") or "").upper() != str(
        plan.get("direction") or ""
    ).upper():
        return False
    saved_low = _f(saved_geometry.get("candidate_low"))
    saved_high = _f(saved_geometry.get("candidate_high"))
    plan_low = _f(plan.get("entry_low"))
    plan_high = _f(plan.get("entry_high"))
    if None in {saved_low, saved_high, plan_low, plan_high}:
        return False
    assert saved_low is not None and saved_high is not None
    assert plan_low is not None and plan_high is not None
    return abs(saved_low - plan_low) <= 0.05 and abs(saved_high - plan_high) <= 0.05


def build_canonical_xau_decision(
    *,
    v226_evaluation: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    price_now: float | None,
    path_direction: str | None = None,
    saved_v229_geometry: dict[str, Any] | None = None,
    zone_probabilities: list[dict[str, Any]] | None = None,
    v226_age_seconds: float | None = None,
    atlas_age_seconds: float | None = None,
) -> dict[str, Any]:
    """Build one read-only, non-misleading XAU decision state for Streamlit.

    V182/current-path direction is the operational display authority. V226 remains
    locator/depth research and can only provide executable geometry when its
    candidate is aligned with the current path and V229 can rebuild the plan.
    """

    focus_direction = str(v226_evaluation.get("focus_direction") or "").upper()
    requested_path_side = str(path_direction or "").upper()
    px = _f(price_now)
    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    active_path_side = str(active_path.get("reaction_direction") or "").upper()

    # Current structural path wins over the research locator. A stale/misaligned
    # V226 focus is diagnostic only and must never flip the user-facing direction.
    direction = (
        requested_path_side
        if requested_path_side in {"LONG", "SHORT"}
        else active_path_side
        if active_path_side in {"LONG", "SHORT"}
        else focus_direction
        if focus_direction in {"LONG", "SHORT"}
        else ""
    )
    direction_source = (
        "V182_CURRENT_PATH"
        if requested_path_side in {"LONG", "SHORT"} or active_path_side in {"LONG", "SHORT"}
        else "V226_RESEARCH_FALLBACK"
        if direction
        else "UNAVAILABLE"
    )

    diagnostics: list[str] = []
    blocking_conflicts: list[str] = []
    if (
        focus_direction in {"LONG", "SHORT"}
        and direction in {"LONG", "SHORT"}
        and focus_direction != direction
    ):
        diagnostics.append("DIRECTION_V226_VS_CURRENT_PATH")

    stale_reasons: list[str] = []
    if v226_age_seconds is not None and v226_age_seconds > 600.0:
        stale_reasons.append("V226_STALE")
    if atlas_age_seconds is not None and atlas_age_seconds > 900.0:
        stale_reasons.append("ATLAS_STALE")

    raw_candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    candidate_direction = str(raw_candidate.get("direction") or "").upper()
    candidate_aligned = bool(
        raw_candidate
        and direction in {"LONG", "SHORT"}
        and candidate_direction in {"", direction}
    )
    candidate = dict(raw_candidate) if candidate_aligned else {}
    if raw_candidate and not candidate_aligned:
        diagnostics.append("V226_CANDIDATE_DIRECTION_MISMATCH")
    historical_context = dict(candidate.get("historical_context") or {})

    nearest_demand = _nearest_active_zone(
        atlas_evaluation,
        direction="LONG",
        price=px,
    )
    nearest_supply = _nearest_active_zone(
        atlas_evaluation,
        direction="SHORT",
        price=px,
    )

    path = {}
    if (
        active_path
        and str(active_path.get("reaction_direction") or "").upper() == direction
    ):
        path = active_path
    elif direction in {"LONG", "SHORT"}:
        path = _path_for_direction(atlas_evaluation, direction)

    active_source_raw = dict(path.get("source_zone") or {})
    active_source = (
        _zone_text(active_source_raw)
        if _active_zone(active_source_raw)
        and str(active_source_raw.get("direction") or "").upper() == direction
        else {}
    )
    nearest_same_direction = (
        nearest_demand
        if direction == "LONG"
        else nearest_supply
        if direction == "SHORT"
        else {}
    )
    operational_source = dict(active_source or nearest_same_direction or {})

    local_structure_supersedes = bool(
        candidate
        and operational_source
        and _local_zone_supersedes_candidate(
            direction=direction,
            price=px,
            candidate=candidate,
            local_zone=operational_source,
        )
    )

    can_build_v229 = bool(
        px is not None
        and candidate
        and not local_structure_supersedes
        and (
            focus_direction not in {"LONG", "SHORT"}
            or focus_direction == direction
        )
    )
    current_plan = (
        build_parent_ladder_plan(
            v226_evaluation=v226_evaluation,
            atlas_evaluation=atlas_evaluation,
            live_price=px,
        )
        if can_build_v229
        else None
    )

    saved_geometry = dict(saved_v229_geometry or {})
    saved_match = bool(
        current_plan and _saved_geometry_matches(saved_geometry, current_plan)
    )
    if saved_geometry and current_plan and not saved_match:
        diagnostics.append("SAVED_V229_GEOMETRY_MISMATCH")
        blocking_conflicts.append("SAVED_V229_GEOMETRY_MISMATCH")

    remap_reasons: list[str] = []
    local_structure_override: dict[str, Any] = {}
    if local_structure_supersedes:
        remap_reasons.append("LOCAL_STRUCTURE_AHEAD_OF_V226_CANDIDATE")
        local_structure_override = dict(operational_source)
    elif operational_source and not current_plan and (
        not candidate or not candidate_aligned
    ):
        # No aligned V229 candidate exists. Show the current structural source as
        # a watch zone, never the old opposite-side V226 locator.
        local_structure_override = dict(operational_source)

    if current_plan:
        direction = str(current_plan.get("direction") or direction).upper()
        entry_low = _f(current_plan.get("entry_low"))
        entry_high = _f(current_plan.get("entry_high"))
        entry_reference = _f(current_plan.get("entry"))
        stop = _f(current_plan.get("sl"))
        tp1 = _f(current_plan.get("tp1"))
        tp2 = _f(current_plan.get("tp2"))
        rr1 = _f(current_plan.get("rr1"))
        rr2 = _f(current_plan.get("rr2"))
        targets = _collect_structural_targets(current_plan)
        authority = "V229_CANONICAL_GEOMETRY"
        candidate_key = str(current_plan.get("candidate_key") or "")
        source_layer = str(current_plan.get("source_layer") or "")
        h4_zone_id = str(current_plan.get("h4_zone_id") or "")
        active_entry_zone = {
            "low": entry_low,
            "high": entry_high,
            "reference": entry_reference,
            "role": "CANONICAL_ENTRY",
        }
    elif local_structure_override:
        entry_low = _f(local_structure_override.get("low"))
        entry_high = _f(local_structure_override.get("high"))
        proximal = _f(local_structure_override.get("proximal"))
        entry_reference = (
            proximal
            if proximal is not None
            else (entry_low + entry_high) / 2.0
            if entry_low is not None and entry_high is not None
            else None
        )
        stop = None
        tp1 = None
        tp2 = None
        rr1 = None
        rr2 = None
        targets = []
        authority = "LOCAL_STRUCTURE_WATCH_NO_V229_AUTHORITY"
        candidate_key = ""
        source_layer = (
            "ATLAS_LOCAL_"
            + str(local_structure_override.get("timeframe") or "STRUCTURE").upper()
            + "_WATCH"
        )
        h4_zone_id = ""
        active_entry_zone = {
            "low": entry_low,
            "high": entry_high,
            "reference": entry_reference,
            "role": "WATCH_NOT_ENTRY",
        }
    elif candidate:
        entry_low = _f(candidate.get("entry_low"))
        entry_high = _f(candidate.get("entry_high"))
        entry_reference = _f(candidate.get("entry_reference"))
        stop = None
        tp1 = None
        tp2 = None
        rr1 = None
        rr2 = None
        targets = []
        authority = "PREPARE_ONLY_NO_V229_PLAN"
        candidate_key = ""
        source_layer = str(candidate.get("source_layer") or "")
        side_map = dict(v226_evaluation.get(direction.lower()) or {})
        h4_zone_id = str(
            dict(dict(side_map.get("h4") or {}).get("zone") or {}).get("zone_id")
            or ""
        )
        active_entry_zone = {
            "low": entry_low,
            "high": entry_high,
            "reference": entry_reference,
            "role": "V226_PREPARE_ONLY",
        }
    else:
        entry_low = None
        entry_high = None
        entry_reference = None
        stop = None
        tp1 = None
        tp2 = None
        rr1 = None
        rr2 = None
        targets = []
        authority = "NO_CURRENT_ENTRY_GEOMETRY"
        candidate_key = ""
        source_layer = ""
        h4_zone_id = ""
        active_entry_zone = {}

    reaction_target = dict(path.get("reaction_target") or {})
    terminal_zone = _zone_text(
        dict(
            path.get("terminal_target_zone")
            or path.get("primary_opposing_zone")
            or {}
        )
    )
    likely_destination = (
        dict(targets[0])
        if targets
        else {
            "target_price": _f(reaction_target.get("price")),
            "timeframe": str(terminal_zone.get("timeframe") or ""),
            "zone_id": str(terminal_zone.get("zone_id") or ""),
            "role": (
                "CANONICAL_TP"
                if current_plan
                else "PATH_TARGET_WATCH_NOT_ORDER_TP"
            ),
            "zone_low": terminal_zone.get("low"),
            "zone_high": terminal_zone.get("high"),
            "rr": None,
        }
    )

    primary_reversal_watch = _primary_reversal_watch(
        atlas_evaluation,
        direction=direction,
        price=px,
        zone_probabilities=zone_probabilities,
    )

    state = "WAIT"
    if stale_reasons:
        state = "STALE_WAIT"
    elif blocking_conflicts:
        state = "CONFLICT_WAIT"
    elif remap_reasons:
        state = "LOCAL_REMAP_WAIT"
    elif current_plan:
        state = "CANONICAL_PLAN_READY"
    elif local_structure_override:
        state = "LOCAL_PATH_WATCH"
    elif entry_low is not None and entry_high is not None:
        state = "DEPTH_PREPARE_ONLY"

    return {
        "contract": "XAU_CANONICAL_DECISION_V240_2",
        "state": state,
        "direction": direction,
        "direction_source": direction_source,
        "v226_focus_direction": focus_direction,
        "candidate_direction": candidate_direction,
        "price_now": px,
        "authority": authority,
        "entry_authorized": bool(
            current_plan
            and not stale_reasons
            and not blocking_conflicts
        ),
        "candidate_key": candidate_key,
        "source_layer": source_layer,
        "h4_zone_id": h4_zone_id,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference": entry_reference,
        "active_entry_zone": active_entry_zone,
        "active_path_source": active_source,
        "sl": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rr1": rr1,
        "rr2": rr2,
        "structural_targets": targets,
        "likely_destination": likely_destination,
        "terminal_opposing_zone": terminal_zone,
        "nearest_demand": nearest_demand,
        "nearest_supply": nearest_supply,
        "primary_reversal_watch": primary_reversal_watch,
        "historical_context": historical_context,
        "depth": {
            "display_status": str(candidate.get("display_status") or ""),
            "approach_state": str(candidate.get("approach_state") or ""),
            "distance_points": _f(candidate.get("distance_points")),
            "calibrated_fresh_first_touch": bool(
                candidate.get("calibrated_fresh_first_touch")
            ),
        },
        "saved_geometry_match": saved_match,
        "conflicts": diagnostics,
        "blocking_conflicts": blocking_conflicts,
        "stale_reasons": stale_reasons,
        "remap_reasons": remap_reasons,
        "local_structure_override": local_structure_override,
        "execution_influence": False,
        "live_execution_enabled": False,
    }


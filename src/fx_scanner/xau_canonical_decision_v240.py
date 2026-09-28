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


def _nearest_active_zone(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
    price: float | None,
) -> dict[str, Any]:
    candidates: list[tuple[float, float, dict[str, Any]]] = []
    for raw in list(atlas_evaluation.get("zones") or []):
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
    """True when an active same-direction atlas zone sits between price and V226.

    V226 is intentionally H4-parent hierarchical. That can leave a valid but very
    distant nested locator selected while a newer standalone H1/M15 structural zone
    has formed closer to price. The dashboard must not label the distant locator as
    the primary entry in that case. This helper is display/fail-closed only; it does
    not grant execution authority to the local atlas zone.
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
    """Build one read-only decision state for Streamlit.

    Entry/SL/TP uses the same V229 parent-ladder builder as the DEMO execution
    worker. If current V229 geometry cannot be rebuilt, the dashboard remains
    PREPARE/WAIT and does not promote legacy path values into executable levels.
    """

    focus_direction = str(v226_evaluation.get("focus_direction") or "").upper()
    path_side = str(path_direction or "").upper()
    px = _f(price_now)

    conflicts: list[str] = []
    if focus_direction in {"LONG", "SHORT"} and path_side in {"LONG", "SHORT"}:
        if focus_direction != path_side:
            conflicts.append("DIRECTION_V226_VS_PATH")

    stale_reasons: list[str] = []
    if v226_age_seconds is not None and v226_age_seconds > 600.0:
        stale_reasons.append("V226_STALE")
    if atlas_age_seconds is not None and atlas_age_seconds > 900.0:
        stale_reasons.append("ATLAS_STALE")

    candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    historical_context = dict(candidate.get("historical_context") or {})
    provisional_direction = (
        focus_direction
        if focus_direction in {"LONG", "SHORT"}
        else path_side
    )

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
    provisional_local_zone = (
        nearest_demand
        if provisional_direction == "LONG"
        else nearest_supply
        if provisional_direction == "SHORT"
        else {}
    )
    local_structure_supersedes = _local_zone_supersedes_candidate(
        direction=provisional_direction,
        price=px,
        candidate=candidate,
        local_zone=provisional_local_zone,
    )

    # Fail closed when a newer/closer same-direction structure is physically
    # between price and the hierarchical V226 locator. V229 may continue to wait
    # for a valid H4-parent candidate, but V240 must not present the old distant
    # locator as the primary current entry.
    current_plan = (
        None
        if local_structure_supersedes
        else (
            build_parent_ladder_plan(
                v226_evaluation=v226_evaluation,
                atlas_evaluation=atlas_evaluation,
                live_price=px,
            )
            if px is not None
            else None
        )
    )

    direction = (
        str(current_plan.get("direction") or "").upper()
        if current_plan
        else provisional_direction
    )

    saved_geometry = dict(saved_v229_geometry or {})
    saved_match = bool(current_plan and _saved_geometry_matches(saved_geometry, current_plan))
    if saved_geometry and current_plan and not saved_match:
        conflicts.append("SAVED_V229_GEOMETRY_MISMATCH")

    remap_reasons: list[str] = []
    local_structure_override: dict[str, Any] = {}
    if local_structure_supersedes:
        remap_reasons.append("LOCAL_STRUCTURE_AHEAD_OF_V226_CANDIDATE")
        local_structure_override = dict(provisional_local_zone)

    if current_plan:
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
    elif local_structure_supersedes:
        entry_low = _f(local_structure_override.get("low"))
        entry_high = _f(local_structure_override.get("high"))
        proximal = _f(local_structure_override.get("proximal"))
        if proximal is not None:
            entry_reference = proximal
        elif entry_low is not None and entry_high is not None:
            entry_reference = (entry_low + entry_high) / 2.0
        else:
            entry_reference = None
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
    else:
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
        h4_zone_id = str(dict(dict(side_map.get("h4") or {}).get("zone") or {}).get("zone_id") or "")

    path = _path_for_direction(atlas_evaluation, direction)
    reaction_target = dict(path.get("reaction_target") or {})
    terminal_zone = _zone_text(dict(path.get("terminal_target_zone") or {}))
    likely_destination = (
        dict(targets[0]) if targets else {
            "target_price": _f(reaction_target.get("price")),
            "timeframe": "",
            "zone_id": str(terminal_zone.get("zone_id") or ""),
            "role": "ATLAS_REACTION_TARGET",
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
    if conflicts:
        state = "CONFLICT_WAIT"
    elif stale_reasons:
        state = "STALE_WAIT"
    elif remap_reasons:
        state = "LOCAL_REMAP_WAIT"
    elif current_plan:
        state = "CANONICAL_PLAN_READY"
    elif entry_low is not None and entry_high is not None:
        state = "DEPTH_PREPARE_ONLY"

    return {
        "contract": "XAU_CANONICAL_DECISION_V240_1",
        "state": state,
        "direction": direction,
        "price_now": px,
        "authority": authority,
        "candidate_key": candidate_key,
        "source_layer": source_layer,
        "h4_zone_id": h4_zone_id,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_reference": entry_reference,
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
        "conflicts": conflicts,
        "stale_reasons": stale_reasons,
        "remap_reasons": remap_reasons,
        "local_structure_override": local_structure_override,
        "execution_influence": False,
        "live_execution_enabled": False,
    }

from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

CONTRACT = "RIZAN_STYLE_PATH_ENGINE_V303"
DISPLAY_NAME = "RIZAN STYLE PATH ENGINE"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "STRUCTURAL_FORECAST_ONLY"


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
    if lifecycle and lifecycle.get("active") is False:
        return False
    status = str(zone.get("status") or "").upper()
    return "BROKEN" not in status and "INVALID" not in status


def _compact_zone(zone: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(zone or {})
    if not row:
        return {}
    return {
        "zone_id": str(row.get("zone_id") or ""),
        "timeframe": str(row.get("timeframe") or "").upper(),
        "direction": str(row.get("direction") or "").upper(),
        "low": _f(row.get("low")),
        "high": _f(row.get("high")),
        "proximal": _f(row.get("proximal")),
        "distal": _f(row.get("distal")),
        "status": str(row.get("status") or ""),
        "research_score": _f(row.get("research_score")),
        "distance_atr": _f(row.get("distance_atr")),
        "lifecycle": dict(row.get("lifecycle") or {}),
    }


def _zone_bounds(zone: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    return low, high


def _distance_to_zone(price: float | None, zone: dict[str, Any]) -> float | None:
    bounds = _zone_bounds(zone)
    if price is None or bounds is None:
        return None
    low, high = bounds
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _zone_relation(price: float | None, zone: dict[str, Any]) -> str:
    bounds = _zone_bounds(zone)
    if price is None or bounds is None:
        return "UNKNOWN"
    low, high = bounds
    direction = str(zone.get("direction") or "").upper()
    if low <= price <= high:
        return "INSIDE"
    if direction == "SHORT":
        return "REACTION_SIDE" if price < low else "BREAK_SIDE"
    if direction == "LONG":
        return "REACTION_SIDE" if price > high else "BREAK_SIDE"
    return "OUTSIDE"


def _key_levels(zone: dict[str, Any]) -> dict[str, Any]:
    bounds = _zone_bounds(zone)
    if bounds is None:
        return {}
    low, high = bounds
    side = str(zone.get("direction") or "").upper()
    if side == "SHORT":
        reclaim = low
        break_level = high
        reject_rule = "M5/M15 close back below supply proximal after touch"
        break_rule = "M15 close accepts above supply distal"
    elif side == "LONG":
        reclaim = high
        break_level = low
        reject_rule = "M5/M15 close back above demand proximal after touch"
        break_rule = "M15 close accepts below demand distal"
    else:
        reclaim = (low + high) / 2.0
        break_level = None
        reject_rule = "WAIT_DIRECTION"
        break_rule = "WAIT_DIRECTION"
    return {
        "rejection_reclaim_key": reclaim,
        "break_acceptance_key": break_level,
        "midpoint": (low + high) / 2.0,
        "rejection_rule": reject_rule,
        "acceptance_rule": break_rule,
    }


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


def _zone_identity(zone: dict[str, Any]) -> tuple[Any, ...]:
    zone_id = str(zone.get("zone_id") or "")
    if zone_id:
        return ("ID", zone_id)
    return (
        "GEOMETRY",
        str(zone.get("timeframe") or "").upper(),
        str(zone.get("direction") or "").upper(),
        _f(zone.get("low")),
        _f(zone.get("high")),
    )


def _dedupe_zones(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in rows:
        row = dict(raw or {})
        if not row:
            continue
        key = _zone_identity(row)
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _route_waypoints(path: dict[str, Any], *, direction: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_price: set[float] = set()

    def add_point(price: Any, source: str, role: str) -> None:
        parsed = _f(price)
        if parsed is None:
            return
        key = round(parsed, 4)
        if key in seen_price:
            return
        seen_price.add(key)
        output.append({"price": parsed, "source": source, "role": role})

    for row in list(path.get("checkpoint_targets") or []):
        item = dict(row or {})
        add_point(item.get("price"), str(item.get("source") or "CHECKPOINT"), "CHECKPOINT")

    for row in list(path.get("internal_targets") or []):
        item = dict(row or {})
        add_point(item.get("price"), str(item.get("source") or "INTERNAL"), "INTERNAL")

    target = dict(path.get("reaction_target") or {})
    add_point(target.get("price"), str(target.get("source") or "REACTION_TARGET"), "REACTION_TARGET")

    for raw in list(path.get("destination_stack") or []):
        zone = dict(raw or {})
        bounds = _zone_bounds(zone)
        if bounds is None:
            continue
        low, high = bounds
        proximal = low if direction == "LONG" else high
        add_point(proximal, f"{str(zone.get('timeframe') or '').upper()}_ZONE", "DECISION_ZONE")

    output.sort(key=lambda row: float(row["price"]), reverse=direction == "SHORT")
    return output[:12]


def _destination_stack(path: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _compact_zone(row)
        for row in _dedupe_zones(
            [
                dict(path.get("primary_opposing_zone") or {}),
                dict(path.get("terminal_target_zone") or {}),
                *[dict(item or {}) for item in list(path.get("destination_stack") or [])],
            ]
        )
        if _active_zone(dict(row or {}))
    ]


def _decision_zone(
    *,
    active_path: dict[str, Any],
    price: float | None,
) -> tuple[dict[str, Any], str]:
    source = dict(active_path.get("source_zone") or {})
    source_relation = _zone_relation(price, source)
    if _active_zone(source) and source_relation == "INSIDE":
        return source, "CURRENT_SOURCE_REACTION"

    destinations = _destination_stack(active_path)
    for zone in destinations:
        relation = _zone_relation(price, zone)
        if relation in {"INSIDE", "REACTION_SIDE"}:
            return zone, "NEXT_OPPOSING_DECISION"

    if destinations:
        return destinations[0], "NEXT_OPPOSING_DECISION"
    if _active_zone(source):
        return source, "CURRENT_SOURCE_WATCH"
    return {}, "UNAVAILABLE"


def _matching_m5_leg(
    atlas_evaluation: dict[str, Any],
    *,
    decision_zone: dict[str, Any],
) -> dict[str, Any]:
    projection = dict(
        atlas_evaluation.get("m5_path_projection")
        or dict(atlas_evaluation.get("path_map") or {}).get("m5_path_projection")
        or {}
    )
    wanted = _zone_identity(decision_zone)
    for leg_name in ("next_leg", "current_leg"):
        leg = dict(projection.get(leg_name) or {})
        source = dict(leg.get("source_zone") or {})
        if source and _zone_identity(source) == wanted:
            out = dict(leg)
            out["leg_name"] = leg_name
            return out
    return {}


def _research_evidence(
    zone: dict[str, Any],
    zone_probabilities: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    zone_id = str(zone.get("zone_id") or "")
    if not zone_id:
        return {}
    for raw in list(zone_probabilities or []):
        row = dict(raw or {})
        if str(row.get("zone_id") or "") != zone_id:
            continue
        destination = dict(row.get("destination") or {})
        reaction = dict(row.get("reaction") or {})
        return {
            "p_touch_research": _f(destination.get("p_touch")),
            "p_reaction_050_research": _f(reaction.get("p_hold_050")),
            "p_break_research": _f(reaction.get("p_break")),
            "confidence": str(reaction.get("confidence") or ""),
            "estimate_type": str(reaction.get("estimate_type") or ""),
            "not_calibrated_probability_claim": bool(
                reaction.get("not_calibrated_probability_claim", True)
            ),
        }
    return {}


def _next_destination_after_break(
    active_path: dict[str, Any],
    *,
    decision_zone: dict[str, Any],
) -> dict[str, Any]:
    stack = _destination_stack(active_path)
    wanted = _zone_identity(decision_zone)
    found = False
    for zone in stack:
        if _zone_identity(zone) == wanted:
            found = True
            continue
        if found:
            return zone
    return {}


def build_rizan_style_path_engine(
    *,
    atlas_evaluation: dict[str, Any],
    price_now: float | None = None,
    path_direction: str | None = None,
    zone_probabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a branching structural route map without creating order authority.

    The engine converts the existing V182 supply/demand map into the user-facing
    sequence used by RIZAN: current source -> next decision zone -> rejection
    branch or acceptance branch -> next destination. It intentionally does not
    duplicate V229 execution logic and cannot authorize an order.
    """

    price = _f(price_now)
    if price is None:
        price = _f(atlas_evaluation.get("last_closed_m15_price"))

    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    requested = str(path_direction or "").upper()
    active_direction = str(active_path.get("reaction_direction") or "").upper()
    direction = (
        requested
        if requested in {"LONG", "SHORT"}
        else active_direction
        if active_direction in {"LONG", "SHORT"}
        else ""
    )
    if direction not in {"LONG", "SHORT"}:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "NO_STRUCTURAL_PATH",
            "price_now": price,
            "active_direction": None,
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "policy_effect": POLICY_EFFECT,
        }

    if not active_path or str(active_path.get("reaction_direction") or "").upper() != direction:
        active_path = _path_for_direction(atlas_evaluation, direction)

    source_zone = _compact_zone(dict(active_path.get("source_zone") or {}))
    decision_zone_raw, decision_role = _decision_zone(
        active_path=active_path,
        price=price,
    )
    decision_zone = _compact_zone(decision_zone_raw)
    relation = _zone_relation(price, decision_zone)
    keys = _key_levels(decision_zone)

    m5_leg = _matching_m5_leg(
        atlas_evaluation,
        decision_zone=decision_zone,
    )
    micro = dict(m5_leg.get("micro_refinement") or {})
    micro_state = str(micro.get("state") or "").upper()
    decision_side = str(decision_zone.get("direction") or "").upper()
    rejection_confirmed = bool(
        decision_zone
        and decision_side in {"LONG", "SHORT"}
        and str(m5_leg.get("direction") or "").upper() == decision_side
        and micro_state == "M5_REFINEMENT_CONFIRMED_SHADOW"
    )

    if not decision_zone:
        state = "NO_DECISION_ZONE"
    elif relation == "INSIDE":
        state = "DECISION_ZONE_ACTIVE"
    elif relation == "BREAK_SIDE":
        state = "DECISION_ZONE_ACCEPTED_BREAK"
    elif rejection_confirmed:
        state = "DECISION_ZONE_REJECTION_CONFIRMED"
    else:
        state = "APPROACH_DECISION_ZONE"

    primary_route = _route_waypoints(active_path, direction=direction)
    rejection_direction = decision_side if decision_side in {"LONG", "SHORT"} else (
        "SHORT" if direction == "LONG" else "LONG"
    )
    rejection_path = _path_for_direction(atlas_evaluation, rejection_direction)
    rejection_source = dict(rejection_path.get("source_zone") or {})
    rejection_source_matches = bool(
        decision_zone and rejection_source and _zone_identity(decision_zone) == _zone_identity(rejection_source)
    )
    rejection_route = _route_waypoints(
        rejection_path,
        direction=rejection_direction,
    )

    next_after_break = _next_destination_after_break(
        active_path,
        decision_zone=decision_zone,
    )
    acceptance_direction = direction

    branch_preference = (
        "REJECTION_BRANCH"
        if state == "DECISION_ZONE_REJECTION_CONFIRMED"
        else "ACCEPTANCE_BRANCH"
        if state == "DECISION_ZONE_ACCEPTED_BREAK"
        else "WAIT_DECISION"
    )

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": state,
        "price_now": price,
        "active_direction": direction,
        "decision_role": decision_role,
        "decision_zone_relation": relation,
        "active_source_zone": source_zone,
        "next_decision_zone": decision_zone,
        "key_levels": keys,
        "branch_preference": branch_preference,
        "primary_path": {
            "direction": direction,
            "state": str(active_path.get("state") or ""),
            "route": primary_route,
            "destination_stack": _destination_stack(active_path),
            "condition": "Continue toward the next structural decision zone while the active source remains valid.",
        },
        "rejection_branch": {
            "direction": rejection_direction,
            "armed": rejection_confirmed,
            "source_matches_decision_zone": rejection_source_matches,
            "route": rejection_route if rejection_source_matches else [],
            "condition": str(keys.get("rejection_rule") or "WAIT_REJECTION"),
            "m5_state": micro_state or None,
            "m5_leg": str(m5_leg.get("leg_name") or "") or None,
        },
        "acceptance_branch": {
            "direction": acceptance_direction,
            "armed": state == "DECISION_ZONE_ACCEPTED_BREAK",
            "condition": str(keys.get("acceptance_rule") or "WAIT_ACCEPTANCE"),
            "next_destination_zone": _compact_zone(next_after_break),
        },
        "research_evidence": _research_evidence(
            decision_zone,
            zone_probabilities,
        ),
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "policy_effect": POLICY_EFFECT,
        "note": (
            "RIZAN STYLE PATH ENGINE is a branching structural forecast. "
            "It maps source -> decision zone -> rejection/acceptance branches. "
            "V229/V280/admission/protection remain the only path to DEMO execution."
        ),
    }

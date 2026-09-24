from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Sequence

from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .models import Bar

CONTRACT = "XAU_BIDIRECTIONAL_M5_PATH_V196"


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = _f(a.get("low"))
    a_high = _f(a.get("high"))
    b_low = _f(b.get("low"))
    b_high = _f(b.get("high"))
    if None in {a_low, a_high, b_low, b_high}:
        return 0.0
    assert a_low is not None and a_high is not None
    assert b_low is not None and b_high is not None
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    span = max(a_high - a_low, b_high - b_low, 1e-12)
    return overlap / span


def _same_zone(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if not a or not b:
        return False
    a_id = str(a.get("zone_id") or "")
    b_id = str(b.get("zone_id") or "")
    if a_id and b_id and a_id == b_id:
        return True
    return _zone_overlap(a, b) > 0.0


def _next_precision_source(
    active_path: dict[str, Any],
    *,
    current_terminal: dict[str, Any],
    next_direction: str,
) -> dict[str, Any]:
    if not current_terminal:
        return {}

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in (
        list(active_path.get("destination_stack") or [])
        + list(active_path.get("secondary_opposing_zones") or [])
    ):
        item = dict(raw or {})
        if not item:
            continue
        zone_id = str(item.get("zone_id") or "")
        if zone_id and zone_id in seen:
            continue
        if zone_id:
            seen.add(zone_id)
        item_direction = str(item.get("direction") or "").upper()
        if item_direction and item_direction != next_direction:
            continue
        if str(item.get("timeframe") or "").upper() != "H1":
            continue
        if not _same_zone(item, current_terminal):
            continue
        lifecycle = dict(item.get("lifecycle") or {})
        if lifecycle and lifecycle.get("active") is False:
            continue
        candidates.append(item)

    if candidates:
        if next_direction == "SHORT":
            candidates.sort(key=lambda item: (_f(item.get("low")) or float("inf")))
        else:
            candidates.sort(
                key=lambda item: -(_f(item.get("high")) or float("-inf"))
            )
        return candidates[0]

    return dict(current_terminal)


def _target_snapshot(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "reaction_target": dict(path.get("reaction_target") or {}),
        "terminal_target_zone": dict(
            path.get("terminal_target_zone")
            or path.get("primary_opposing_zone")
            or {}
        ),
        "target_ladder": list(path.get("target_ladder") or []),
    }


def _leg_payload(
    *,
    direction: str,
    path: dict[str, Any],
    micro: dict[str, Any],
) -> dict[str, Any]:
    refined = dict(micro.get("refined_entry_pocket") or {})
    candidate = dict(micro.get("candidate_entry_pocket") or {})
    micro_state = str(micro.get("state") or "").upper()
    invalidated = "INVALIDATED" in micro_state

    if invalidated:
        pocket = {}
        pocket_state = "INVALIDATED_M5_POCKET"
    else:
        pocket = refined or candidate
        pocket_state = (
            "REFINED_M5_POCKET"
            if refined
            else "CANDIDATE_M5_POCKET"
            if candidate
            else "NO_M5_POCKET_YET"
        )

    return {
        "direction": direction,
        "path_state": path.get("state"),
        "source_role": path.get("source_role"),
        "source_zone": dict(path.get("source_zone") or {}),
        "micro_refinement": micro,
        "pocket_state": pocket_state,
        "m5_pocket": pocket,
        "historical_candidate_pocket": candidate if invalidated else {},
        **_target_snapshot(path),
    }


def evaluate_bidirectional_m5_path(
    m5_bars: Sequence[Bar],
    *,
    path_map: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    active_path = dict(path_map.get("active_path") or {})
    direction = str(active_path.get("reaction_direction") or "").upper()

    base = {
        "contract": CONTRACT,
        "policy_effect": "SHADOW_PREPARE_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    if direction not in {"LONG", "SHORT"} or not active_path:
        return base | {
            "state": "NO_ACTIVE_PATH",
            "current_leg": {},
            "next_leg": {},
        }

    current_micro = evaluate_micro_refinement(
        m5_bars,
        path_map={"active_path": active_path},
        as_of=as_of,
    )
    current_leg = _leg_payload(
        direction=direction,
        path=active_path,
        micro=current_micro,
    )

    next_direction = "SHORT" if direction == "LONG" else "LONG"
    next_path_key = "supply_to_demand" if next_direction == "SHORT" else "demand_to_supply"
    reverse_template = dict(path_map.get(next_path_key) or {})
    current_terminal = dict(
        active_path.get("terminal_target_zone")
        or active_path.get("primary_opposing_zone")
        or {}
    )

    if current_terminal:
        next_source = _next_precision_source(
            active_path,
            current_terminal=current_terminal,
            next_direction=next_direction,
        )
        next_path = dict(reverse_template)
        next_path["reaction_direction"] = next_direction
        next_path["source_zone"] = next_source
        next_path["source_role"] = (
            "H1_PRECISION_INSIDE_CURRENT_TERMINAL"
            if str(next_source.get("timeframe") or "").upper() == "H1"
            else "CURRENT_TERMINAL_OPPOSING_ZONE"
        )
        next_path["state"] = "SOURCE_ZONE_WATCH"
    else:
        next_path = reverse_template
        next_source = dict(next_path.get("source_zone") or {})

    target_source_aligned = _same_zone(current_terminal, next_source)

    if next_path and next_source:
        next_micro = evaluate_micro_refinement(
            m5_bars,
            path_map={"active_path": next_path},
            as_of=as_of,
        )
        next_leg = _leg_payload(
            direction=next_direction,
            path=next_path,
            micro=next_micro,
        )
        next_leg["parent_matches_current_terminal"] = target_source_aligned
        next_leg["activation_rule"] = (
            "The next opposing leg must originate from the current leg terminal opposing "
            "zone, preferably an active H1 precision source nested inside it. It remains "
            "watch-only until fresh M5 touch/sweep, reclaim, causal MSS and displacement."
        )
    else:
        next_leg = {
            "direction": next_direction,
            "path_state": "NO_REVERSE_PATH",
            "source_zone": current_terminal,
            "micro_refinement": {},
            "pocket_state": "NO_M5_POCKET_YET",
            "m5_pocket": {},
            "reaction_target": {},
            "terminal_target_zone": {},
            "target_ladder": [],
            "parent_matches_current_terminal": False,
            "activation_rule": (
                "No reverse path is currently available; keep the opposing zone as watch-only."
            ),
        }

    if current_leg.get("pocket_state") == "REFINED_M5_POCKET":
        state = "CURRENT_LEG_REFINED_NEXT_LEG_PREMAPPED"
    elif current_leg.get("pocket_state") == "CANDIDATE_M5_POCKET":
        state = "CURRENT_LEG_CANDIDATE_NEXT_LEG_PREMAPPED"
    else:
        state = "PATH_PREMAPPED_WAIT_M5"

    return base | {
        "state": state,
        "current_leg": current_leg,
        "next_leg": next_leg,
        "interpretation": (
            "V196 maps both legs without creating entry authority. The current leg carries "
            "its M5 pocket plus reaction/terminal targets. The next opposing leg is anchored "
            "to the current terminal opposing zone and prefers an active nested H1 precision "
            "source. It is only called an M5 pocket after fresh M5 evidence exists."
        ),
    }

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


def _latched_current_precision_path(
    active_path: dict[str, Any],
    *,
    previous_projection: dict[str, Any] | None,
    direction: str,
) -> tuple[dict[str, Any], bool]:
    """Keep an already-observed H1 precision source across an HTF source handoff.

    The atlas can legitimately promote an overlapping H4/D1 parent to active_path
    while an H1 child already owns a live M5 candidate/refined pocket. V189 only
    refines H1 sources, so dropping that child makes the pocket disappear even
    though price has not invalidated it. This latch is deliberately narrow:
    it only reuses the immediately previous current-leg H1 source when it overlaps
    the new HTF parent, has the same direction, has availability metadata, and
    already carried actual M5 pocket evidence.

    The source is re-evaluated against the current M5 bars on every cycle. V219
    deliberately allows a previously invalidated H1 child to be re-evaluated
    inside the still-valid overlapping H4/D1 parent: the H1 break may be the
    liquidity sweep that creates the actual parent reversal. V189 decides
    whether the parent-rescue contract is valid; otherwise this function falls
    back to the HTF parent exactly as before.
    """
    current_source = dict(active_path.get("source_zone") or {})
    if not current_source:
        return active_path, False
    if str(current_source.get("timeframe") or "").upper() == "H1":
        return active_path, False

    previous = dict(previous_projection or {})
    previous_leg = dict(previous.get("current_leg") or {})
    previous_source = dict(previous_leg.get("source_zone") or {})
    previous_micro = dict(previous_leg.get("micro_refinement") or {})

    if str(previous_source.get("timeframe") or "").upper() != "H1":
        return active_path, False
    previous_direction = str(
        previous_leg.get("direction")
        or previous_source.get("direction")
        or previous_micro.get("direction")
        or ""
    ).upper()
    if previous_direction != direction:
        return active_path, False
    if not previous_source.get("available_at"):
        return active_path, False
    if not _same_zone(previous_source, current_source):
        return active_path, False

    previous_state = str(previous_micro.get("state") or "").upper()
    previous_pocket = (
        dict(previous_leg.get("m5_pocket") or {})
        or dict(previous_leg.get("historical_candidate_pocket") or {})
        or dict(previous_micro.get("refined_entry_pocket") or {})
        or dict(previous_micro.get("candidate_entry_pocket") or {})
    )
    if not previous_pocket:
        return active_path, False

    latched = dict(active_path)
    latched["parent_source_zone"] = current_source
    latched["source_zone"] = previous_source
    latched["source_role"] = (
        "LATCHED_INVALIDATED_H1_INSIDE_ACTIVE_HTF_PARENT"
        if "INVALIDATED" in previous_state
        else "LATCHED_H1_PRECISION_INSIDE_ACTIVE_HTF_PARENT"
    )
    latched["previous_h1_micro_state"] = previous_state
    return latched, True


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
    previous_projection: dict[str, Any] | None = None,
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

    current_eval_path, precision_source_latched = _latched_current_precision_path(
        active_path,
        previous_projection=previous_projection,
        direction=direction,
    )
    parent_context = (
        dict(current_eval_path.get("parent_source_zone") or {})
        if precision_source_latched
        else {}
    )
    current_micro = evaluate_micro_refinement(
        m5_bars,
        path_map={"active_path": current_eval_path},
        as_of=as_of,
        parent_source_zone=parent_context,
    )

    # V218: if the H1 child is invalid but the overlapping HTF parent remains
    # valid, V189 may retain the causal micro reversal as shadow evidence.
    # Otherwise fall back exactly as before.
    if precision_source_latched and "INVALIDATED" in str(
        current_micro.get("state") or ""
    ).upper():
        current_eval_path = active_path
        precision_source_latched = False
        current_micro = evaluate_micro_refinement(
            m5_bars,
            path_map={"active_path": active_path},
            as_of=as_of,
        )

    current_leg = _leg_payload(
        direction=direction,
        path=current_eval_path,
        micro=current_micro,
    )
    current_leg["precision_source_latched"] = precision_source_latched
    if precision_source_latched:
        current_leg["parent_source_zone"] = dict(
            current_eval_path.get("parent_source_zone") or {}
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
            "its M5 pocket plus reaction/terminal targets, and an existing H1 precision source "
            "is latched across an overlapping H4/D1 parent handoff until current M5 evidence "
            "invalidates it. The next opposing leg is anchored "
            "to the current terminal opposing zone and prefers an active nested H1 precision "
            "source. It is only called an M5 pocket after fresh M5 evidence exists."
        ),
    }

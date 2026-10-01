from __future__ import annotations

from math import isfinite
from typing import Any

CONTRACT = "XAU_RIZAN_SIMPLE_DECISION_V336_1"
DISPLAY_NAME = "RIZAN SIMPLE DECISION"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone_bounds(zone: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    return low, high


def _zone_kind(zone: dict[str, Any]) -> str:
    side = str(zone.get("direction") or "").upper()
    if side == "LONG":
        return "DEMAND"
    if side == "SHORT":
        return "SUPPLY"
    return "ZONE"


def _price_relation(price_now: float | None, zone: dict[str, Any]) -> str:
    bounds = _zone_bounds(zone)
    if price_now is None or bounds is None:
        return "UNKNOWN"
    low, high = bounds
    if low <= price_now <= high:
        return "INSIDE"
    side = str(zone.get("direction") or "").upper()
    if side == "LONG":
        return "ABOVE" if price_now > high else "BELOW"
    if side == "SHORT":
        return "BELOW" if price_now < low else "ABOVE"
    return "OUTSIDE"


def _primary_micro(micro_evaluation: dict[str, Any]) -> dict[str, Any]:
    return dict(
        micro_evaluation.get("primary")
        or micro_evaluation
        or {}
    )


def build_simple_decision(
    *,
    price_now: float | None,
    path_engine: dict[str, Any],
    micro_evaluation: dict[str, Any],
    canonical_decision: dict[str, Any],
    reversal_stage: dict[str, Any],
    admission_label: str,
    backend_stale: bool,
    position_mode: bool,
    effective_entry_authorized: bool,
) -> dict[str, Any]:
    """Collapse research engines into one human-readable market story.

    The key distinction is intentional:
    - travel_direction = where price is travelling now;
    - reversal_direction = the expected reaction direction at the next decision zone.

    Opposite values are therefore not presented as contradictory votes.
    """

    path = dict(path_engine or {})
    canonical = dict(canonical_decision or {})
    stage = dict(reversal_stage or {})
    micro_eval = dict(micro_evaluation or {})
    micro = _primary_micro(micro_eval)

    primary_path = dict(path.get("primary_path") or {})
    decision_zone = dict(path.get("next_decision_zone") or {})
    key_levels = dict(path.get("key_levels") or {})
    acceptance_branch = dict(path.get("acceptance_branch") or {})
    rejection_branch = dict(path.get("rejection_branch") or {})

    px = _f(price_now)
    travel_direction = str(
        path.get("active_direction")
        or primary_path.get("direction")
        or canonical.get("direction")
        or "WAIT"
    ).upper()
    reversal_direction = str(
        decision_zone.get("direction")
        or rejection_branch.get("direction")
        or micro.get("direction")
        or "WAIT"
    ).upper()
    micro_direction = str(
        micro.get("direction")
        or micro_eval.get("direction")
        or "WAIT"
    ).upper()
    micro_phase = str(
        micro.get("phase")
        or micro_eval.get("phase")
        or "WAIT"
    ).upper()
    relation = str(
        path.get("decision_zone_relation")
        or _price_relation(px, decision_zone)
    ).upper()

    stage_name = str(stage.get("stage") or "PREPARE").upper()
    hard_block = bool(stage.get("hard_execution_block"))
    stage_demo_allowed = bool(stage.get("demo_entry_allowed")) and not hard_block

    canonical_direction = str(canonical.get("direction") or travel_direction or "WAIT").upper()
    admitted = bool(
        effective_entry_authorized
        and stage_demo_allowed
        and not backend_stale
    )

    if backend_stale:
        action = "DATA STALE — NO ORDER"
        action_class = "BLOCKED"
    elif position_mode:
        action = "MANAGE POSITION"
        action_class = "MANAGE"
    elif admitted:
        action = f"{canonical_direction} — ENTRY READY"
        action_class = "ENTRY_READY"
    elif stage_name in {"SETUP_INVALID", "BREAK_RISK", "MISSED_ENTRY_WAIT_NEXT_SETUP"}:
        action = "NO ORDER — WAIT SETUP BARU"
        action_class = "BLOCKED"
    elif relation == "INSIDE" and reversal_direction in {"LONG", "SHORT"}:
        if stage_name in {"REACTION_VISIBLE", "M5_CONFIRMATION"}:
            action = f"WAIT ADMISSION {reversal_direction}"
            action_class = "CONFIRMING"
        else:
            action = f"WAIT REVERSAL {reversal_direction}"
            action_class = "REVERSAL_WATCH"
    elif travel_direction in {"LONG", "SHORT"} and decision_zone:
        action = f"TRAVEL {travel_direction} → {_zone_kind(decision_zone)}"
        action_class = "TRAVEL"
    else:
        action = "WAIT — BELUM ADA PATH BERSIH"
        action_class = "WAIT"

    geometry = {
        "entry": _f(canonical.get("entry_reference")),
        "entry_low": _f(canonical.get("entry_low")),
        "entry_high": _f(canonical.get("entry_high")),
        "sl": _f(canonical.get("sl")),
        "tp1": _f(canonical.get("tp1")),
        "tp2": _f(canonical.get("tp2")),
    }
    if not admitted:
        geometry = {
            "entry": None,
            "entry_low": None,
            "entry_high": None,
            "sl": None,
            "tp1": None,
            "tp2": None,
        }

    acceptance_direction = str(
        acceptance_branch.get("direction")
        or travel_direction
        or "WAIT"
    ).upper()
    rejection_direction = str(
        rejection_branch.get("direction")
        or reversal_direction
        or "WAIT"
    ).upper()

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "price_now": px,
        "action": action,
        "action_class": action_class,
        "travel_direction": travel_direction,
        "reversal_direction": reversal_direction,
        "micro_direction": micro_direction,
        "micro_phase": micro_phase,
        "decision_zone": decision_zone,
        "decision_zone_kind": _zone_kind(decision_zone),
        "decision_zone_relation": relation,
        "reversal_stage": stage_name,
        "admission_label": str(admission_label or "WAIT"),
        "entry_authorized": admitted,
        "geometry": geometry,
        "rejection_scenario": {
            "direction": rejection_direction,
            "trigger": key_levels.get("rejection_rule"),
            "key": _f(key_levels.get("rejection_reclaim_key")),
        },
        "acceptance_scenario": {
            "direction": acceptance_direction,
            "trigger": key_levels.get("acceptance_rule"),
            "key": _f(key_levels.get("break_acceptance_key")),
            "next_destination_zone": dict(
                acceptance_branch.get("next_destination_zone") or {}
            ),
        },
        "travel_vs_reversal": (
            "SEQUENTIAL_NOT_CONFLICT"
            if travel_direction in {"LONG", "SHORT"}
            and reversal_direction in {"LONG", "SHORT"}
            and travel_direction != reversal_direction
            else "ALIGNED_OR_UNRESOLVED"
        ),
        "explanation": (
            "Travel direction describes the move into the next decision zone. "
            "Reversal direction describes the reaction to watch only after price reaches that zone. "
            "Entry/SL/TP are hidden until the canonical DEMO admission path is actually authorized."
        ),
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
    }

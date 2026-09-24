from __future__ import annotations

from typing import Any

CONTRACT = "XAU_ZONE_REUSE_CONTROLLER_V200"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def evaluate_zone_reuse(
    zone: dict[str, Any] | None,
    *,
    micro_refinement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    zone = dict(zone or {})
    lifecycle = dict(zone.get("lifecycle") or {})
    micro = dict(micro_refinement or {})
    active = bool(lifecycle.get("active", False))
    freshness = str(lifecycle.get("freshness") or "UNKNOWN").upper()
    touches = _i(lifecycle.get("touch_count"))
    mitigation = _f(lifecycle.get("mitigation_depth"))
    micro_state = str(micro.get("state") or "NO_MICRO_EVIDENCE").upper()
    refined = dict(micro.get("refined_entry_pocket") or {})
    candidate = dict(micro.get("candidate_entry_pocket") or {})

    micro_invalidated = "INVALIDATED" in micro_state
    fresh_micro_confirmed = bool(
        refined
        and micro.get("mss_confirmed")
        and micro.get("reclaim_confirmed")
        and micro.get("displacement_confirmed")
        and not micro_invalidated
    )

    if not zone:
        state = "NO_PARENT_ZONE"
        parent_mapping_allowed = False
        refresh_required = True
        priority = "SEARCH_NEW_PARENT_ZONE"
    elif not active or freshness == "BROKEN":
        state = "PARENT_ZONE_RETIRED"
        parent_mapping_allowed = False
        refresh_required = True
        priority = "SEARCH_NEW_PARENT_ZONE"
    elif mitigation >= 0.75:
        if fresh_micro_confirmed:
            state = "DEEPLY_MITIGATED_REUSE_WITH_FRESH_MICRO_ONLY"
            priority = "MICRO_REFRESH_CONFIRMED_SHADOW"
        else:
            state = "DEEPLY_MITIGATED_REQUIRE_NEW_MICRO"
            priority = "SEARCH_NEW_CHILD_M5"
        parent_mapping_allowed = True
        refresh_required = True
    elif mitigation >= 0.35:
        if fresh_micro_confirmed:
            state = "PARTIALLY_MITIGATED_REUSE_WITH_FRESH_MICRO"
            priority = "MICRO_REFRESH_CONFIRMED_SHADOW"
        else:
            state = "PARTIALLY_MITIGATED_REQUIRE_RECONFIRMATION"
            priority = "WAIT_FRESH_M5_CONFIRMATION"
        parent_mapping_allowed = True
        refresh_required = True
    elif touches == 0:
        state = "FRESH_PARENT_ZONE"
        parent_mapping_allowed = True
        refresh_required = False
        priority = "PREFERRED_WATCH"
    elif touches == 1:
        state = "FIRST_TEST_PARENT_ACTIVE"
        parent_mapping_allowed = True
        refresh_required = False
        priority = "WATCH_WITH_CONFIRMATION"
    elif touches == 2:
        state = "SECOND_TEST_CONDITIONAL"
        parent_mapping_allowed = True
        refresh_required = True
        priority = "PREFER_NEW_MICRO_CONFIRMATION"
    else:
        if fresh_micro_confirmed:
            state = "MULTI_TESTED_REUSE_WITH_FRESH_MICRO"
            priority = "MICRO_REFRESH_CONFIRMED_SHADOW"
        else:
            state = "MULTI_TESTED_REQUIRE_NEW_MICRO"
            priority = "SEARCH_NEW_CHILD_M5"
        parent_mapping_allowed = True
        refresh_required = True

    if micro_invalidated and parent_mapping_allowed:
        state = (
            "PARENT_CONTEXT_ONLY_MICRO_INVALIDATED"
            if mitigation < 0.75
            else "DEEPLY_MITIGATED_MICRO_INVALIDATED"
        )
        refresh_required = True
        priority = "SEARCH_NEW_CHILD_M5"

    return {
        "contract": CONTRACT,
        "state": state,
        "priority": priority,
        "parent_zone_id": zone.get("zone_id"),
        "parent_direction": zone.get("direction"),
        "timeframe": zone.get("timeframe"),
        "touch_count": touches,
        "mitigation_depth": mitigation,
        "freshness": freshness,
        "parent_mapping_allowed": parent_mapping_allowed,
        "blind_reuse_allowed": False,
        "fresh_micro_refresh_required": refresh_required,
        "fresh_micro_confirmed": fresh_micro_confirmed,
        "micro_state": micro_state,
        "active_refined_micro_pocket": refined,
        "active_candidate_micro_pocket": candidate if not micro_invalidated else {},
        "hard_touch_limit": None,
        "interpretation": (
            "There is no fixed universal touch-count expiry. The parent zone may remain "
            "mapped while structurally active, but repeated/deep mitigation requires fresh "
            "M5 sweep/reclaim/MSS/displacement evidence. Broken zones are retired."
        ),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def evaluate_bidirectional_reuse(
    projection: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = dict(projection or {})
    output: dict[str, Any] = {
        "contract": CONTRACT,
        "current_leg": {},
        "next_leg": {},
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    for leg_name in ("current_leg", "next_leg"):
        leg = dict(projection.get(leg_name) or {})
        output[leg_name] = evaluate_zone_reuse(
            dict(leg.get("source_zone") or {}),
            micro_refinement=dict(leg.get("micro_refinement") or {}),
        )
    return output

from __future__ import annotations

import hashlib
from math import isfinite
from typing import Any

from .demo_xau_structural_targets_v229 import (
    build_structural_target_plan,
    runtime_m15_target_zones,
)

CHILD_LOT = 0.01
MAX_CHILDREN = 4
MIN_TERMINAL_RR = 1.50
H4_STOP_BUFFER_ATR = 0.15


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _target_pool(atlas_evaluation: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    m15 = runtime_m15_target_zones(list(atlas_evaluation.get("chart_bars_m15") or []))
    path_map = dict(atlas_evaluation.get("path_map") or {})
    zones: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(atlas_evaluation.get("zones") or []):
        zone = dict(raw or {})
        key = str(zone.get("zone_id") or "")
        if key and key not in seen:
            seen.add(key)
            zones.append(zone)
    for key in ("demand_to_supply", "supply_to_demand"):
        path = dict(path_map.get(key) or {})
        for raw in list(path.get("destination_stack") or []):
            zone = dict(raw or {})
            zid = str(zone.get("zone_id") or "")
            if zid and zid not in seen:
                seen.add(zid)
                zones.append(zone)
    return m15, zones


def _slot_target(targets: list[dict[str, Any]], slot: int) -> dict[str, Any] | None:
    if not targets:
        return None
    if slot == 1:
        return dict(targets[0])
    if slot == 2 and len(targets) >= 2:
        return dict(targets[1])
    return dict(targets[-1])


def _limit_valid_now(direction: str, entry: float, live_price: float) -> bool:
    if direction == "LONG":
        return entry < live_price
    return entry > live_price


def build_parent_ladder_plan(
    *,
    v226_evaluation: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    live_price: float,
) -> dict[str, Any] | None:
    direction = str(v226_evaluation.get("focus_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None

    # V182 current structural path is the operational direction authority.
    # V226 is a locator/depth engine; if its focus has not remapped yet, never
    # let the older locator create or keep a DEMO execution parent.
    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    active_direction = str(active_path.get("reaction_direction") or "").upper()
    if active_direction in {"LONG", "SHORT"} and active_direction != direction:
        return None

    candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    candidate_direction = str(candidate.get("direction") or "").upper()
    if candidate_direction in {"LONG", "SHORT"} and candidate_direction != direction:
        return None
    fresh_pre_touch = bool(
        candidate.get(
            "pre_touch_execution_eligible",
            candidate.get("calibrated_fresh_first_touch", False),
        )
    )
    confirmation_allowed = bool(
        candidate.get(
            "confirmation_execution_eligible",
            candidate.get("confirmation_calibrated_first_touch", False)
            or candidate.get("first_touch_in_progress", False),
        )
    )
    confirmation_first_touch = bool(
        candidate.get("confirmation_calibrated_first_touch")
        or candidate.get("first_touch_in_progress")
    )
    retest_confirmation = bool(candidate.get("retest_confirmation_eligible"))
    if not (fresh_pre_touch or confirmation_allowed):
        return None

    display_status = str(candidate.get("display_status") or "")
    allowed_statuses = {
        "PREPARE_ONLY_FRESH_FIRST_TOUCH",
        "CONFIRMATION_ONLY_FIRST_TOUCH_IN_PROGRESS",
        "CONFIRMATION_ONLY_RETESTED_HTF",
        "CONFIRMATION_ONLY_RETESTED_M15",
    }
    if display_status not in allowed_statuses:
        return None
    if fresh_pre_touch and display_status != "PREPARE_ONLY_FRESH_FIRST_TOUCH":
        return None
    if retest_confirmation and display_status not in {
        "CONFIRMATION_ONLY_RETESTED_HTF",
        "CONFIRMATION_ONLY_RETESTED_M15",
    }:
        return None

    low = _f(candidate.get("entry_low"))
    high = _f(candidate.get("entry_high"))
    px = _f(live_price)
    if low is None or high is None or px is None or not 0 < low < high:
        return None

    # Keep execution parity with V240. If the current V182 active source is on
    # the same side but physically sits between live price and the older V226
    # candidate, the local structure supersedes that locator. V229 must remap
    # instead of preserving a far parent that the dashboard correctly hides.
    active_source = dict(active_path.get("source_zone") or {})
    source_lifecycle = dict(active_source.get("lifecycle") or {})
    source_active = bool(active_source) and source_lifecycle.get("active", True) is not False
    source_direction = str(active_source.get("direction") or "").upper()
    source_low = _f(active_source.get("low"))
    source_high = _f(active_source.get("high"))
    if (
        source_active
        and source_direction == direction
        and source_low is not None
        and source_high is not None
        and source_high > source_low
    ):
        if direction == "SHORT" and px <= source_high < low:
            return None
        if direction == "LONG" and high < source_low <= px:
            return None

    side_map = dict(v226_evaluation.get(direction.lower()) or {})
    h4 = dict(dict(side_map.get("h4") or {}).get("zone") or {})
    h4_low = _f(h4.get("low"))
    h4_high = _f(h4.get("high"))
    h4_atr = _f(h4.get("atr_points"))
    if None in {h4_low, h4_high, h4_atr}:
        return None
    assert h4_low is not None and h4_high is not None and h4_atr is not None
    if h4_high <= h4_low or h4_atr <= 0:
        return None
    stop = (
        h4_low - H4_STOP_BUFFER_ATR * h4_atr
        if direction == "LONG"
        else h4_high + H4_STOP_BUFFER_ATR * h4_atr
    )

    source_ladder = dict(v226_evaluation.get("four_order_ladder") or {})
    raw_slots = [dict(x) for x in list(source_ladder.get("slots") or [])]
    if len(raw_slots) != MAX_CHILDREN:
        return None

    m15_targets, htf_targets = _target_pool(atlas_evaluation)
    children: list[dict[str, Any]] = []
    terminal_prices: list[float] = []
    first_targets: list[float] = []

    for slot in raw_slots:
        slot_no = int(slot.get("slot") or 0)
        reference = _f(slot.get("reference_price"))
        if slot_no not in {1, 2, 3, 4} or reference is None:
            return None
        structural = build_structural_target_plan(
            direction=direction,
            entry=reference,
            stop=float(stop),
            m15_zones=m15_targets,
            htf_zones=htf_targets,
            minimum_rr=MIN_TERMINAL_RR,
        )
        targets = [dict(x) for x in list(structural.get("broker_scaleout_targets") or [])]
        chosen = _slot_target(targets, slot_no)
        target_price = None if chosen is None else _f(chosen.get("target_price"))
        if target_price is not None:
            terminal_prices.append(target_price)
            first_targets.append(target_price)
        pretouch = slot_no <= 2
        execution_enabled = bool(fresh_pre_touch or not pretouch)
        children.append(
            {
                **slot,
                "slot": slot_no,
                "lot": CHILD_LOT,
                "reference_price": reference,
                "planned_entry": reference if pretouch and execution_enabled else None,
                "planned_sl": float(stop),
                "planned_tp": target_price,
                "target_timeframe": None if chosen is None else chosen.get("timeframe"),
                "target_zone_id": None if chosen is None else chosen.get("zone_id"),
                "structural_targets": list(structural.get("mapped_targets") or []),
                "terminal_rr_eligible": bool(structural.get("terminal_rr_eligible")),
                "submit_eligible": bool(
                    execution_enabled
                    and pretouch
                    and target_price is not None
                    and _limit_valid_now(direction, reference, px)
                ),
                "execution_enabled": execution_enabled,
                "execution_mode": (
                    "LIMIT_PRE_TOUCH"
                    if pretouch and execution_enabled
                    else "DISABLED_CONFIRMATION_ONLY"
                    if pretouch
                    else "LIMIT_ON_M5_RETEST"
                ),
            }
        )

    enabled_children = [c for c in children if c.get("planned_tp") is not None]
    if not enabled_children:
        return None

    execution_phase = (
        "PRE_TOUCH"
        if fresh_pre_touch
        else "RETEST_CONFIRMATION"
        if retest_confirmation
        else "FIRST_TOUCH_CONFIRMATION"
    )
    candidate_key = "|".join(
        (
            "XAU_RIZAN_DEPTH_EXECUTION_V1",
            direction,
            str(h4.get("zone_id") or ""),
            str(candidate.get("source_layer") or ""),
            execution_phase,
            f"{low:.5f}",
            f"{high:.5f}",
        )
    )
    digest = hashlib.sha256(candidate_key.encode()).hexdigest()[:18]
    midpoint = (low + high) / 2.0
    risk = midpoint - stop if direction == "LONG" else stop - midpoint
    if risk <= 0:
        return None
    ordered_targets = sorted(
        {float(c["planned_tp"]) for c in enabled_children},
        reverse=direction == "SHORT",
    )
    first_tp = ordered_targets[0]
    terminal_tp = ordered_targets[-1]
    rr1 = (
        (first_tp - midpoint) / risk
        if direction == "LONG"
        else (midpoint - first_tp) / risk
    )
    rr2 = (
        (terminal_tp - midpoint) / risk
        if direction == "LONG"
        else (midpoint - terminal_tp) / risk
    )

    return {
        "contract": "XAU_RIZAN_DEPTH_CHILD_LADDER_V229_1",
        "plan_id": f"RZ229-{digest}",
        "candidate_key": candidate_key,
        "direction": direction,
        "entry_low": low,
        "entry_high": high,
        "entry": midpoint,
        "sl": float(stop),
        "tp1": float(first_tp),
        "tp2": float(terminal_tp),
        "rr1": float(rr1),
        "rr2": float(rr2),
        "source_layer": str(candidate.get("source_layer") or ""),
        "h4_zone_id": str(h4.get("zone_id") or ""),
        "candidate": candidate,
        "children": children,
        "max_children": MAX_CHILDREN,
        "child_lot": CHILD_LOT,
        "max_total_lot": CHILD_LOT * MAX_CHILDREN,
        "execution_phase": execution_phase,
        "pretouch_slots": [1, 2] if fresh_pre_touch else [],
        "confirmation_slots": [3, 4],
        "zone_reuse": dict(candidate.get("zone_reuse") or {}),
        "retest_confirmation_required": retest_confirmation,
        "m15_retest_confirmation_required": bool(
            candidate.get("m15_retest_confirmation_required")
        ),
        "live_price_at_plan": px,
        "generic_market_handoff_allowed": False,
        "environment": "DEMO",
        "live_execution_enabled": False,
    }


def child_client_order_id(plan_id: str, slot: int) -> str:
    digest = hashlib.sha256(str(plan_id).encode()).hexdigest()[:18]
    return f"RZ229:{digest}:L{int(slot)}"

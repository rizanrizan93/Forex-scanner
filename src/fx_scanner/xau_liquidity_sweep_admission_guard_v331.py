from __future__ import annotations

from math import isfinite
from typing import Any

from .xau_liquidity_pool_envelope_v328 import build_liquidity_pool_envelope
from .xau_rizan_style_path_engine_v303 import build_rizan_style_path_engine

CONTRACT = "XAU_LIQUIDITY_SWEEP_ADMISSION_GUARD_V331_1"
POLICY_EFFECT = "DEMO_EXECUTION_GUARD_ONLY"
EXECUTION_INFLUENCE = True
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False


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


def _source_zone(plan: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(plan.get("candidate") or {})
    for raw in (
        candidate.get("source_zone"),
        plan.get("source_zone"),
    ):
        zone = dict(raw or {})
        if _zone_bounds(zone) is not None:
            return zone
    return {}


def _aligned_source(
    *,
    plan_direction: str,
    source_zone: dict[str, Any],
    decision_zone: dict[str, Any],
) -> bool:
    decision_direction = str(decision_zone.get("direction") or "").upper()
    if plan_direction not in {"LONG", "SHORT"} or decision_direction != plan_direction:
        return False

    source_id = str(source_zone.get("zone_id") or "")
    decision_id = str(decision_zone.get("zone_id") or "")
    if source_id and decision_id and source_id == decision_id:
        return True

    source_bounds = _zone_bounds(source_zone)
    decision_bounds = _zone_bounds(decision_zone)
    if source_bounds is None or decision_bounds is None:
        return False
    source_low, source_high = source_bounds
    decision_low, decision_high = decision_bounds
    return bool(source_high >= decision_low and decision_high >= source_low)


def _micro_rows(
    *,
    atlas_evaluation: dict[str, Any],
    plan_direction: str,
) -> list[dict[str, Any]]:
    atlas = dict(atlas_evaluation or {})
    projection = dict(atlas.get("m5_path_projection") or {})
    current_leg = dict(projection.get("current_leg") or {})
    next_leg = dict(projection.get("next_leg") or {})
    rows = [
        dict(atlas.get("micro_refinement") or {}),
        dict(current_leg.get("micro_refinement") or {}),
        dict(next_leg.get("micro_refinement") or {}),
    ]
    output: list[dict[str, Any]] = []
    for row in rows:
        if not row:
            continue
        direction = str(row.get("direction") or "").upper()
        if direction and direction != plan_direction:
            continue
        output.append(row)
    return output


def _micro_confirmed(
    *,
    atlas_evaluation: dict[str, Any],
    plan_direction: str,
) -> tuple[bool, dict[str, Any]]:
    for row in _micro_rows(
        atlas_evaluation=atlas_evaluation,
        plan_direction=plan_direction,
    ):
        state = str(row.get("state") or "").upper()
        reclaim = bool(row.get("reclaim_confirmed"))
        mss = bool(row.get("mss_confirmed"))
        displacement = bool(row.get("displacement_confirmed"))
        if (
            state in {
                "M5_REFINEMENT_CONFIRMED_SHADOW",
                "M5_REFINEMENT_CONFIRMED",
                "CONFIRMED",
            }
            or (reclaim and mss and displacement)
        ):
            return True, {
                "state": state or "CONFIRMED_FLAGS",
                "reclaim_confirmed": reclaim,
                "mss_confirmed": mss,
                "displacement_confirmed": displacement,
                "reclaim_at": row.get("reclaim_at"),
                "mss_at": row.get("mss_at"),
                "displacement_at": row.get("displacement_at"),
            }
    return False, {}


def build_liquidity_sweep_admission_guard(
    *,
    atlas_evaluation: dict[str, Any],
    plan: dict[str, Any],
    live_price: float | None,
) -> dict[str, Any]:
    """Fail closed on zone-edge fading when a sweep envelope is still unresolved.

    V331 is intentionally asymmetric: it can block a DEMO entry but never grant
    entry authority. A medium/high V328 sweep warning on the same source zone
    disables pre-touch/zone-edge entry until M5 reclaim + MSS + displacement is
    causally confirmed.
    """
    atlas = dict(atlas_evaluation or {})
    plan_row = dict(plan or {})
    direction = str(
        plan_row.get("direction")
        or dict(plan_row.get("candidate") or {}).get("direction")
        or ""
    ).upper()
    source = _source_zone(plan_row)

    style_path = build_rizan_style_path_engine(
        atlas_evaluation=atlas,
        price_now=live_price,
    )
    liquidity = build_liquidity_pool_envelope(
        atlas_evaluation=atlas,
        style_path=style_path,
        price_now=live_price,
    )
    decision_zone = dict(liquidity.get("decision_zone") or {})
    aligned = _aligned_source(
        plan_direction=direction,
        source_zone=source,
        decision_zone=decision_zone,
    )
    risk = str(liquidity.get("risk_grade") or "LOW").upper()
    warning = bool(liquidity.get("first_touch_warning"))
    micro_ok, micro = _micro_confirmed(
        atlas_evaluation=atlas,
        plan_direction=direction,
    )

    relevant_warning = bool(
        aligned
        and risk in {"MEDIUM", "HIGH"}
        and warning
    )
    hard_block = bool(relevant_warning and not micro_ok)

    if hard_block:
        state = "WAIT_LIQUIDITY_SWEEP_CONFIRMATION"
        reason = (
            "ZONE_EDGE_FADE_BLOCKED_UNTIL_M5_RECLAIM_MSS_DISPLACEMENT"
        )
    elif relevant_warning and micro_ok:
        state = "SWEEP_RISK_RECONFIRMED"
        reason = "M5_RECLAIM_MSS_DISPLACEMENT_CONFIRMED"
    elif not aligned:
        state = "NOT_ALIGNED_TO_CURRENT_EXECUTION_SOURCE"
        reason = "LIQUIDITY_MAP_CONTEXT_ONLY"
    else:
        state = "NO_ACTIVE_SWEEP_BLOCK"
        reason = "LIQUIDITY_RISK_NOT_HIGH_OR_NO_EXTENSION"

    return {
        "contract": CONTRACT,
        "state": state,
        "reason": reason,
        "direction": direction or None,
        "source_zone_id": source.get("zone_id"),
        "decision_zone_id": decision_zone.get("zone_id"),
        "source_aligned": aligned,
        "risk_grade": risk,
        "first_touch_warning": warning,
        "price_relation": liquidity.get("price_relation"),
        "sweep_band": dict(liquidity.get("sweep_band") or {}),
        "primary_liquidity_pool": dict(
            liquidity.get("primary_liquidity_pool") or {}
        ),
        "micro_reconfirmation": micro,
        "micro_reconfirmed": micro_ok,
        "hard_execution_block": hard_block,
        "pre_touch_entry_allowed": not hard_block,
        "zone_edge_fade_allowed": not hard_block,
        "required_confirmation": (
            "M5_RECLAIM_PLUS_MSS_PLUS_DISPLACEMENT"
            if relevant_warning else None
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "interpretation": (
            "V331 never predicts that liquidity must be swept. It only prevents "
            "a DEMO reversal entry at the edge of an aligned medium/high-risk "
            "liquidity envelope until the existing M5 reversal confirmation is complete."
        ),
        "liquidity_map": liquidity,
    }

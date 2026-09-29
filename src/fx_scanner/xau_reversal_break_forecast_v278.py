from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from .xau_dynamic_depth_hazard_v251 import normalized_depth

CONTRACT = "XAU_REVERSAL_BREAK_FORECAST_V278"
POLICY_EFFECT = "FORECAST_SHADOW_PLUS_EXECUTION_SAFETY_DIAGNOSTIC"
EXECUTION_AUTHORITY = False

_REACTION_HORIZON_MINUTES = {"M15": 240, "H1": 480, "H4": 960}
_REVERSAL_PRESSURE = {
    "OPPOSING_FADING_EARLY",
    "OPPOSING_FADING",
    "FADING_EARLY",
    "BALANCED_ABSORPTION",
    "CONTROL_FLIP",
}
_BREAK_PRESSURE = {"OPPOSING_REACCELERATION", "OPPOSING_STILL_ACTIVE"}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _active_source(
    *,
    v226_evaluation: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    direction: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = dict(v226_evaluation.get("depth_entry_candidate") or {})
    source = dict(candidate.get("source_zone") or {})
    profile = dict(candidate.get("source_profile") or {})
    if source and str(source.get("direction") or direction).upper() == direction:
        return candidate, source, profile

    active_path = dict(dict(atlas_evaluation.get("path_map") or {}).get("active_path") or {})
    path_source = dict(active_path.get("source_zone") or {})
    if (
        str(active_path.get("reaction_direction") or "").upper() == direction
        and path_source
    ):
        return candidate, path_source, profile
    return candidate, {}, profile


def _competing_row(profile: dict[str, Any], depth: float | None) -> dict[str, Any]:
    rows = [dict(row) for row in list(profile.get("oos_2025_2026_competing_risk_bands") or [])]
    if not rows or depth is None or depth < 0.0:
        return {}
    index = min(9, max(0, int(min(float(depth), 0.999999) * 10.0)))
    return {} if index >= len(rows) else dict(rows[index])


def _terminal_target(plan: dict[str, Any], direction: str) -> float | None:
    targets: list[float] = []
    for child in list(plan.get("children") or []):
        for raw in list(dict(child).get("structural_targets") or []):
            price = _f(dict(raw).get("target_price"))
            if price is not None:
                targets.append(price)
    if not targets:
        for key in ("tp2", "tp1"):
            price = _f(plan.get(key))
            if price is not None:
                targets.append(price)
    if not targets:
        return None
    return max(targets) if direction == "LONG" else min(targets)


def _rr_from_market(
    *,
    direction: str,
    price: float | None,
    stop: float | None,
    target: float | None,
) -> float | None:
    if None in {price, stop, target}:
        return None
    assert price is not None and stop is not None and target is not None
    risk = price - stop if direction == "LONG" else stop - price
    reward = target - price if direction == "LONG" else price - target
    return None if risk <= 0.0 or reward <= 0.0 else reward / risk


def _distance_after_band(
    *,
    direction: str,
    price: float | None,
    entry_low: float | None,
    entry_high: float | None,
    atr_points: float | None,
) -> tuple[bool, float | None]:
    if None in {price, entry_low, entry_high}:
        return False, None
    assert price is not None and entry_low is not None and entry_high is not None
    distance = (
        max(0.0, price - entry_high)
        if direction == "LONG"
        else max(0.0, entry_low - price)
    )
    if atr_points is None or atr_points <= 0.0:
        return distance > 0.0, None
    return distance > 0.0, distance / atr_points


def build_reversal_break_forecast(
    *,
    v226_evaluation: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    direction: str,
    price_now: float | None,
    pressure_transition: dict[str, Any] | None = None,
    v229_plan: dict[str, Any] | None = None,
    base_entry_authorized: bool = False,
    now: datetime | None = None,
    minimum_terminal_rr: float = 1.50,
) -> dict[str, Any]:
    """Stage an early reversal forecast without granting execution authority.

    Historical competing risk is first-touch-only evidence. Retests expose the
    same geometry as reference only and require live pressure + M5 confirmation.
    SETUP_INVALID requires actual structural evidence, not historical frequency.
    """
    side = str(direction or "").upper()
    observed_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    pressure = dict(pressure_transition or {})
    plan = dict(v229_plan or {})
    if side not in {"LONG", "SHORT"}:
        return {"contract": CONTRACT, "stage": "WAIT", "reason": "NO_CANONICAL_DIRECTION", "execution_authority": False}

    candidate, source, profile = _active_source(
        v226_evaluation=v226_evaluation,
        atlas_evaluation=atlas_evaluation,
        direction=side,
    )
    if not source:
        return {
            "contract": CONTRACT,
            "stage": "WAIT",
            "reason": "NO_ALIGNED_ACTIVE_SOURCE",
            "direction": side,
            "execution_authority": False,
        }

    lifecycle = dict(source.get("lifecycle") or {})
    touch_count = int(lifecycle.get("touch_count") or source.get("touch_count") or 0)
    prior_scope = (
        "FIRST_TOUCH_CALIBRATED_REFERENCE"
        if touch_count == 0
        else "RETEST_REFERENCE_ONLY_NOT_CALIBRATED"
    )
    depth = None if price_now is None else normalized_depth(source, float(price_now))
    competing = _competing_row(profile, depth)
    p_reversal = _f(competing.get("p_reversal_first"))
    p_break = _f(competing.get("p_break_first"))
    historical_break_dominant = bool(
        p_break is not None and p_reversal is not None and p_break > p_reversal
    )

    micro = dict(
        atlas_evaluation.get("micro_refinement")
        or dict(atlas_evaluation.get("path_map") or {}).get("micro_refinement")
        or {}
    )
    micro_state = str(micro.get("state") or "UNAVAILABLE").upper()
    candidate_pocket = dict(micro.get("candidate_entry_pocket") or micro.get("candidate_pocket") or {})
    refined_pocket = dict(micro.get("refined_entry_pocket") or micro.get("refined_pocket") or {})
    sweep = dict(micro.get("sweep") or {})
    reclaim = bool(micro.get("reclaim_confirmed"))
    mss = bool(micro.get("mss_confirmed"))
    displacement = bool(micro.get("displacement_confirmed"))
    parent_rescue = dict(micro.get("parent_reversal_rescue") or {})

    pressure_state = str(pressure.get("state") or "UNAVAILABLE").upper()
    pressure_hard_block = bool(pressure.get("hard_block"))
    pressure_reversal_support = pressure_state in _REVERSAL_PRESSURE and not pressure_hard_block
    pressure_break_support = pressure_state in _BREAK_PRESSURE or pressure_hard_block

    invalid_reasons: list[str] = []
    if not bool(lifecycle.get("active", True)) or str(lifecycle.get("freshness") or "").upper() == "BROKEN":
        invalid_reasons.append("SOURCE_LIFECYCLE_INACTIVE_OR_BROKEN")
    if micro_state == "SOURCE_INVALIDATED_NO_REFINEMENT":
        invalid_reasons.append("M5_CLOSE_BEYOND_DISTAL")
    if depth is not None and depth >= 1.0 and not bool(parent_rescue.get("active")):
        invalid_reasons.append("PRICE_AT_OR_BEYOND_DISTAL")

    break_risk_reasons: list[str] = []
    if historical_break_dominant:
        break_risk_reasons.append("OOS_FIRST_TOUCH_BREAK_FREQUENCY_EXCEEDS_REVERSAL")
    if pressure_break_support:
        break_risk_reasons.append("LIVE_PRESSURE_SUPPORTS_BREAK")
    if depth is not None and depth >= 0.70:
        break_risk_reasons.append("DEEP_ZONE_PENETRATION")
    if candidate_pocket and not reclaim:
        break_risk_reasons.append("SWEEP_VISIBLE_RECLAIM_NOT_CONFIRMED")

    break_risk = bool(
        not invalid_reasons
        and (
            (
                touch_count == 0
                and historical_break_dominant
                and pressure_break_support
            )
            or (
                touch_count > 0
                and depth is not None
                and depth >= 0.70
                and pressure_break_support
            )
            or (
                depth is not None
                and depth >= 0.90
                and not reclaim
                and pressure_break_support
            )
        )
    )

    entry_low = _f(candidate.get("entry_low"))
    entry_high = _f(candidate.get("entry_high"))
    passed_band, distance_after_band_atr = _distance_after_band(
        direction=side,
        price=price_now,
        entry_low=entry_low,
        entry_high=entry_high,
        atr_points=_f(source.get("atr_points")),
    )
    reaction_visible = bool(candidate_pocket or sweep)
    sweep_at = _dt(sweep.get("at") or candidate_pocket.get("origin_at"))
    reaction_age_minutes = (
        None
        if sweep_at is None
        else max(0.0, (observed_at - sweep_at).total_seconds() / 60.0)
    )
    chase_rr = _rr_from_market(
        direction=side,
        price=price_now,
        stop=_f(plan.get("sl")),
        target=_terminal_target(plan, side),
    )
    no_chase_reasons: list[str] = []
    if reaction_visible and passed_band:
        no_chase_reasons.append("SELECTED_ENTRY_BAND_ALREADY_LEFT_AFTER_REACTION")
    if reaction_visible and distance_after_band_atr is not None and distance_after_band_atr > 0.25:
        no_chase_reasons.append("PRICE_MOVED_GT_0_25_ATR_FROM_SELECTED_BAND")
    if chase_rr is not None and chase_rr < float(minimum_terminal_rr):
        no_chase_reasons.append("CHASE_RR_BELOW_MINIMUM")
    if reaction_visible and passed_band and reaction_age_minutes is not None and reaction_age_minutes > 15.0:
        no_chase_reasons.append("REACTION_ALREADY_OLDER_THAN_15_MIN")
    no_chase = bool(no_chase_reasons)

    inside_zone = bool(depth is not None and 0.0 <= depth < 1.0)
    watch_ready = inside_zone and pressure_reversal_support
    confirmation = reclaim and mss

    if invalid_reasons:
        stage, reason = "SETUP_INVALID", invalid_reasons[0]
    elif no_chase:
        stage, reason = "MISSED_ENTRY_WAIT_NEXT_SETUP", no_chase_reasons[0]
    elif break_risk:
        stage, reason = "BREAK_RISK", break_risk_reasons[0]
    elif base_entry_authorized and confirmation:
        stage, reason = "ENTRY_DEMO_DIIZINKAN", "V229_AUTHORIZED_AND_M5_CONFIRMED"
    elif confirmation:
        stage = "KONFIRMASI_M5"
        reason = "M5_RECLAIM_MSS_DISPLACEMENT_CONFIRMED" if displacement else "M5_RECLAIM_AND_MSS_CONFIRMED"
    elif reaction_visible:
        stage = "REAKSI_TERLIHAT"
        reason = "SWEEP_RECLAIM_VISIBLE_WAIT_MSS" if reclaim else "SWEEP_OR_REJECTION_POCKET_VISIBLE_WAIT_RECLAIM"
    elif watch_ready:
        stage, reason = "REVERSAL_WATCH", "PRICE_IN_ZONE_AND_PRESSURE_WEAKENING_OR_BALANCED"
    elif inside_zone:
        stage, reason = "WAIT", "PRICE_IN_ZONE_BUT_PRESSURE_NOT_SUPPORTIVE"
    else:
        stage, reason = "WAIT", "PRICE_NOT_IN_ACTIVE_REVERSAL_ZONE"

    source_tf = str(source.get("timeframe") or "").upper()
    return {
        "contract": CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "stage": stage,
        "reason": reason,
        "direction": side,
        "alternate_direction": "SHORT" if side == "LONG" else "LONG",
        "price_now": price_now,
        "source_zone": source,
        "source_timeframe": source_tf,
        "touch_count": touch_count,
        "prior_scope": prior_scope,
        "current_depth": depth,
        "current_depth_band": competing.get("band"),
        "competing_risk_reference": (
            {
                **competing,
                "applicability": prior_scope,
                "not_current_calibrated_probability": True,
            }
            if competing
            else {}
        ),
        "historical_reaction_horizon_minutes": _REACTION_HORIZON_MINUTES.get(source_tf),
        "break_risk": {
            "active": break_risk,
            "reasons": break_risk_reasons,
            "historical_break_dominant": historical_break_dominant,
            "live_pressure_break_support": pressure_break_support,
            "invalidation_reasons": invalid_reasons,
            "distal": source.get("distal"),
        },
        "microstructure": {
            "state": micro_state,
            "sweep": sweep,
            "candidate_pocket": candidate_pocket,
            "refined_pocket": refined_pocket,
            "reclaim_confirmed": reclaim,
            "mss_confirmed": mss,
            "displacement_confirmed": displacement,
        },
        "pressure": {
            "state": pressure_state,
            "hard_block": pressure_hard_block,
            "reversal_support": pressure_reversal_support,
            "break_support": pressure_break_support,
            "buyer_index": pressure.get("buyer_index"),
            "seller_index": pressure.get("seller_index"),
        },
        "no_chase": {
            "active": no_chase,
            "reasons": no_chase_reasons,
            "selected_entry_low": entry_low,
            "selected_entry_high": entry_high,
            "distance_after_band_atr": distance_after_band_atr,
            "rr_if_chased_at_market": chase_rr,
            "minimum_terminal_rr": float(minimum_terminal_rr),
            "reaction_age_minutes": reaction_age_minutes,
            "thresholds_are_operational_guards_not_calibrated_probabilities": True,
        },
        "entry_demo": {
            "base_v229_authorized": bool(base_entry_authorized),
            "allowed_by_v278": stage == "ENTRY_DEMO_DIIZINKAN",
            "v278_execution_authority": False,
        },
        "labels": {
            "research": "RISET OOS FIRST-TOUCH 2025-2026",
            "retest": "REFERENCE ONLY — RETEST BELUM TERKALIBRASI",
        },
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": False,
    }

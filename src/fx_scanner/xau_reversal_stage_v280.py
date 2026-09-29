from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any


CONTRACT = "XAU_REVERSAL_STAGE_V280_1"

SUPPORTIVE_PRESSURE_STATES = {
    "OPPOSING_FADING_EARLY",
    "OPPOSING_FADING",
    "FADING_EARLY",
    "BALANCED_ABSORPTION",
    "CONTROL_FLIP",
}
BREAK_PRESSURE_STATES = {
    "OPPOSING_REACCELERATION",
    "OPPOSING_STILL_ACTIVE",
}

# Operational safety thresholds. These are intentionally conservative runtime
# guards, not claims of calibrated reversal/break probabilities.
REACTION_VISIBLE_ATR = 0.10
BAND_PASS_TOLERANCE_ATR = 0.05
DISTAL_ACCEPTANCE_ATR = 0.05
BREAK_RISK_DEPTH = 0.80
SPREAD_ATR_BLOCK = 0.10
REACTION_AGE_WARNING_MINUTES = 30.0


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _source_zone(
    *,
    plan: dict[str, Any],
    atlas_evaluation: dict[str, Any],
) -> dict[str, Any]:
    candidate = dict(plan.get("candidate") or {})
    source = dict(candidate.get("source_zone") or {})
    if source:
        return source
    path = dict(dict(atlas_evaluation.get("path_map") or {}).get("active_path") or {})
    return dict(path.get("source_zone") or {})


def _micro(atlas_evaluation: dict[str, Any]) -> dict[str, Any]:
    return dict(
        atlas_evaluation.get("micro_refinement")
        or dict(atlas_evaluation.get("path_map") or {}).get("micro_refinement")
        or {}
    )


def _selected_band_bounds(plan: dict[str, Any]) -> tuple[float | None, float | None]:
    if bool(plan.get("confirmation_window_only")):
        low = _f(plan.get("confirmation_entry_low"))
        high = _f(plan.get("confirmation_entry_high"))
        if low is not None and high is not None:
            return low, high
    candidate = dict(plan.get("candidate") or {})
    low = _f(candidate.get("entry_low"))
    high = _f(candidate.get("entry_high"))
    if low is None:
        low = _f(plan.get("historical_entry_low"))
    if high is None:
        high = _f(plan.get("historical_entry_high"))
    if low is None:
        low = _f(plan.get("entry_low"))
    if high is None:
        high = _f(plan.get("entry_high"))
    return low, high


def _favorable_reaction_visible(
    *,
    direction: str,
    micro: dict[str, Any],
    atr: float,
    spread: float,
) -> tuple[bool, float | None, float | None]:
    sweep = dict(micro.get("sweep") or {})
    sweep_price = _f(sweep.get("price"))
    last_close = _f(micro.get("last_closed_m5_price"))
    if sweep_price is None or last_close is None:
        return False, sweep_price, last_close
    threshold = max(float(spread) * 2.0, REACTION_VISIBLE_ATR * float(atr))
    if direction == "LONG":
        visible = last_close >= sweep_price + threshold
    elif direction == "SHORT":
        visible = last_close <= sweep_price - threshold
    else:
        visible = False
    return bool(visible), sweep_price, last_close


def _m5_confirmation(micro: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    reclaim = bool(micro.get("reclaim_confirmed"))
    mss = bool(micro.get("mss_confirmed"))
    displacement = bool(micro.get("displacement_confirmed"))
    if reclaim:
        reasons.append("M5_RECLAIM")
    if mss:
        reasons.append("M5_MSS")
    if displacement:
        reasons.append("M5_DISPLACEMENT")
    confirmed = bool((reclaim and mss) or displacement)
    return confirmed, reasons


def _distal_acceptance(
    *,
    direction: str,
    source: dict[str, Any],
    micro: dict[str, Any],
    live_price: float,
    atr: float,
    spread: float,
) -> dict[str, Any]:
    distal = _f(source.get("distal"))
    last_m5 = _f(micro.get("last_closed_m5_price"))
    if distal is None:
        return {
            "live_breach": False,
            "m5_close_acceptance": False,
            "distal": None,
            "buffer": None,
        }
    buffer = max(float(spread) * 2.0, DISTAL_ACCEPTANCE_ATR * float(atr))
    if direction == "LONG":
        live_breach = float(live_price) < distal
        close_accept = last_m5 is not None and last_m5 < distal - buffer
    else:
        live_breach = float(live_price) > distal
        close_accept = last_m5 is not None and last_m5 > distal + buffer
    return {
        "live_breach": bool(live_breach),
        "m5_close_acceptance": bool(close_accept),
        "distal": distal,
        "buffer": float(buffer),
    }


def evaluate_reversal_stage(
    *,
    plan: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    depth_hazard: dict[str, Any],
    pressure_transition: dict[str, Any],
    live_price: float,
    bid: float | None = None,
    ask: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one causal runtime stage for forecast, no-chase and break safety.

    This function deliberately does not turn historical V225 frequencies into a
    current calibrated probability. It combines current geometry/microstructure
    with operational safety rules and returns explicit evidence/reasons.
    """
    current_time = (now or datetime.now(tz=UTC)).astimezone(UTC)
    direction = str(plan.get("direction") or "").upper()
    source = _source_zone(plan=plan, atlas_evaluation=atlas_evaluation)
    lifecycle = dict(source.get("lifecycle") or {})
    micro = _micro(atlas_evaluation)
    atr = _f(source.get("atr_points")) or 0.0
    if atr <= 0.0:
        atr = 1.0
    spread = 0.0
    if bid is not None and ask is not None:
        spread = max(0.0, float(ask) - float(bid))

    depth = _f(depth_hazard.get("current_depth"))
    location = str(depth_hazard.get("location_state") or "")
    pressure_state = str(pressure_transition.get("state") or "UNAVAILABLE")
    hard_pressure_block = bool(pressure_transition.get("hard_block"))
    supportive_pressure = bool(
        pressure_state in SUPPORTIVE_PRESSURE_STATES
        or pressure_transition.get("calibration_entry_allowed")
    )
    breaking_pressure = pressure_state in BREAK_PRESSURE_STATES

    reaction_visible, sweep_price, last_m5 = _favorable_reaction_visible(
        direction=direction,
        micro=micro,
        atr=atr,
        spread=spread,
    )
    m5_confirmed, m5_reasons = _m5_confirmation(micro)
    if bool(micro.get("reclaim_confirmed")):
        reaction_visible = True

    entry_low, entry_high = _selected_band_bounds(plan)
    tolerance = max(spread * 2.0, BAND_PASS_TOLERANCE_ATR * atr)
    passed_band = False
    distance_past_band = 0.0
    if entry_low is not None and entry_high is not None:
        if direction == "LONG" and float(live_price) < entry_low - tolerance:
            passed_band = True
            distance_past_band = entry_low - float(live_price)
        elif direction == "SHORT" and float(live_price) > entry_high + tolerance:
            passed_band = True
            distance_past_band = float(live_price) - entry_high

    distal = _distal_acceptance(
        direction=direction,
        source=source,
        micro=micro,
        live_price=float(live_price),
        atr=atr,
        spread=spread,
    )
    lifecycle_active = bool(lifecycle.get("active", True))
    setup_invalid = bool(
        not lifecycle_active
        or str(lifecycle.get("freshness") or "").upper() == "BROKEN"
        or distal["m5_close_acceptance"]
    )

    spread_atr = spread / atr if atr > 0 else 0.0
    spread_block = bool(spread_atr > SPREAD_ATR_BLOCK)

    historical_scope = str(
        dict(dict(plan.get("candidate") or {}).get("zone_reuse") or {}).get(
            "historical_prior_scope"
        )
        or ""
    )
    first_touch_calibrated = historical_scope == "FIRST_TOUCH_CALIBRATED"

    # Once the original research band has been passed, do not slide the old
    # entry deeper merely to manufacture an order. A later entry needs actual
    # M5 confirmation/new geometry and must still pass RR at the child.
    missed_entry = bool(
        passed_band
        and not setup_invalid
    )

    break_risk = bool(
        not setup_invalid
        and not m5_confirmed
        and (
            distal["live_breach"]
            or (
                depth is not None
                and depth >= BREAK_RISK_DEPTH
                and breaking_pressure
            )
        )
    )

    recommended = dict(depth_hazard.get("recommended_band") or {})
    lower_depth = _f(recommended.get("lower_depth"))
    upper_depth = _f(recommended.get("upper_depth"))
    in_relevant_band = bool(
        location == "INSIDE_ZONE"
        and depth is not None
        and (
            (
                lower_depth is not None
                and upper_depth is not None
                and lower_depth - 1e-9 <= depth <= upper_depth + 1e-9
            )
            or (
                entry_low is not None
                and entry_high is not None
                and entry_low - tolerance <= live_price <= entry_high + tolerance
            )
        )
    )
    reversal_watch = bool(
        in_relevant_band
        and supportive_pressure
        and not setup_invalid
        and not missed_entry
    )

    terminal_rr = _f(plan.get("rr2"))
    terminal_rr_ok = bool(terminal_rr is not None and terminal_rr >= 1.50 - 1e-9)
    strict_pressure_ok = bool(
        not hard_pressure_block
        and (
            pressure_transition.get("pre_touch_entry_allowed")
            or pressure_transition.get("confirmation_entry_allowed")
        )
    )
    demo_entry_allowed = bool(
        plan.get("broker_entry_authorized", True)
        and terminal_rr_ok
        and strict_pressure_ok
        and bool(depth_hazard.get("execution_ready"))
        and m5_confirmed
        and not setup_invalid
        and not missed_entry
        and not break_risk
        and not spread_block
    )

    sweep_at = _dt(dict(micro.get("sweep") or {}).get("at"))
    reaction_age_minutes = (
        None
        if sweep_at is None
        else max(0.0, (current_time - sweep_at).total_seconds() / 60.0)
    )
    reaction_age_warning = bool(
        reaction_visible
        and not m5_confirmed
        and reaction_age_minutes is not None
        and reaction_age_minutes > REACTION_AGE_WARNING_MINUTES
    )

    stage = "PREPARE"
    hard_execution_block = False
    reasons: list[str] = []
    if setup_invalid:
        stage = "SETUP_INVALID"
        hard_execution_block = True
        reasons.append("DISTAL_CLOSE_ACCEPTANCE_OR_ZONE_BROKEN")
    elif break_risk:
        stage = "BREAK_RISK"
        hard_execution_block = True
        reasons.append("BREAKDOWN_EVIDENCE_STRONGER_THAN_REVERSAL")
    elif missed_entry:
        stage = "MISSED_ENTRY_WAIT_NEXT_SETUP"
        hard_execution_block = True
        reasons.append("SELECTED_ENTRY_BAND_PASSED_WITHOUT_M5_CONFIRMATION")
    elif demo_entry_allowed:
        stage = "DEMO_ENTRY_ALLOWED"
        reasons.append("STRICT_PRESSURE_DEPTH_RR_AND_GEOMETRY_READY")
    elif m5_confirmed:
        stage = "M5_CONFIRMATION"
        reasons.extend(m5_reasons or ["M5_CONFIRMATION_VISIBLE"])
    elif reaction_visible:
        stage = "REACTION_VISIBLE"
        reasons.append("FAVORABLE_M5_RESPONSE_AFTER_SWEEP")
    elif reversal_watch:
        stage = "REVERSAL_WATCH"
        reasons.append("RELEVANT_DEPTH_BAND_PLUS_PRESSURE_WEAKENING")
    elif location == "INSIDE_ZONE":
        reasons.append("IN_ZONE_WAIT_REACTION_OR_PRESSURE")
    elif location == "AHEAD_OF_ZONE":
        reasons.append("PRICE_NOT_YET_IN_RELEVANT_ZONE")
    else:
        reasons.append(str(depth_hazard.get("action") or "WAIT"))

    if spread_block:
        hard_execution_block = True
        if stage not in {"SETUP_INVALID", "MISSED_ENTRY_WAIT_NEXT_SETUP"}:
            stage = "BREAK_RISK"
        reasons.append("SPREAD_TOO_LARGE_RELATIVE_TO_SOURCE_ATR")
    if reaction_age_warning:
        reasons.append("REACTION_OLD_WITHOUT_M5_CONFIRMATION")

    return {
        "contract": CONTRACT,
        "stage": stage,
        "hard_execution_block": hard_execution_block,
        "reasons": reasons,
        "direction": direction,
        "live_price": float(live_price),
        "source_zone_id": source.get("zone_id"),
        "source_timeframe": str(source.get("timeframe") or "").upper(),
        "historical_prior_scope": historical_scope,
        "first_touch_calibrated": first_touch_calibrated,
        "depth": depth,
        "location_state": location,
        "recommended_band": recommended,
        "selected_entry_low": entry_low,
        "selected_entry_high": entry_high,
        "passed_selected_band": passed_band,
        "distance_past_selected_band": distance_past_band,
        "band_pass_tolerance": tolerance,
        "reaction_visible": reaction_visible,
        "m5_confirmed": m5_confirmed,
        "m5_confirmation_reasons": m5_reasons,
        "sweep_price": sweep_price,
        "last_closed_m5_price": last_m5,
        "sweep_at": None if sweep_at is None else sweep_at.isoformat(),
        "reaction_age_minutes": reaction_age_minutes,
        "reaction_age_warning": reaction_age_warning,
        "pressure_state": pressure_state,
        "supportive_pressure": supportive_pressure,
        "breaking_pressure": breaking_pressure,
        "spread": spread,
        "spread_atr": spread_atr,
        "spread_block": spread_block,
        "distal": distal,
        "break_risk": break_risk,
        "setup_invalid": setup_invalid,
        "missed_entry": missed_entry,
        "terminal_rr": terminal_rr,
        "terminal_rr_ok": terminal_rr_ok,
        "demo_entry_allowed": demo_entry_allowed,
        "forecast_label": "RISET/FORECAST",
        "calibrated_current_probability": False,
        "interpretation": (
            "Runtime stage combines current geometry, M5 response, pressure, spread and "
            "RR. V225 frequencies remain historical priors only; retests are not treated "
            "as calibrated first-touch probabilities."
        ),
    }

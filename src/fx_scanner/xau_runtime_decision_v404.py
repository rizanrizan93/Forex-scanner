from __future__ import annotations

"""V404 consensus decision layer for the XAUUSD scanner.

V404 combines the local reversal geometry from V390 with the generalized AFIQ
challenger bridge from V403. It is deliberately fail-closed: conflicting,
unavailable, invalidated, or event-blocked inputs cannot become an executable
signal.

This module is decision support only. Promotion to DEMO auto-execution requires
out-of-sample/walk-forward evidence that passes the research gates below. LIVE
auto-execution is never granted by this module.
"""

from typing import Any

from .xau_afiq_scanner_bridge_v403 import evaluate_afiq_scanner_bridge_v403
from .xau_simple_reversal_engine_v390 import evaluate_simple_reversal

CONTRACT = "XAU_RIZAN_RUNTIME_DECISION_V404"
MODE = "SHADOW_CONSENSUS"

RESEARCH_GATES: dict[str, float] = {
    "profit_factor_min": 1.50,
    "expectancy_r_min": 0.04,
    "max_drawdown_pct_max": 15.0,
    "precision_min": 0.60,
    "false_positive_rate_max": 0.40,
    "trades_per_year_min": 24.0,
}

_DIRECTIONAL = {"LONG", "SHORT"}
_V390_READY = {"READY_LONG": "LONG", "READY_SHORT": "SHORT"}
_V403_BLOCKING = {"BLOCKED_EVENT", "INVALIDATED", "UNAVAILABLE"}


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _direction(value: Any) -> str:
    raw = str(value or "WAIT").upper()
    return raw if raw in _DIRECTIONAL else "WAIT"


def _v390_direction(plan: dict[str, Any]) -> str:
    state = str(plan.get("state") or "UNAVAILABLE").upper()
    explicit = _direction(plan.get("direction"))
    return _V390_READY.get(state, explicit)


def _geometry(plan: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    selected = _d(plan.get("selected_zone"))
    entry = _d(plan.get("entry"))
    band = _d(challenger.get("entry_band"))

    low = band.get("low") if band.get("low") is not None else entry.get("low")
    high = band.get("high") if band.get("high") is not None else entry.get("high")
    invalidation = (
        challenger.get("structural_invalidation")
        if challenger.get("structural_invalidation") is not None
        else entry.get("invalidation")
    )
    targets = list(challenger.get("targets") or [])
    if not targets and entry.get("tp1_opposite_local_zone") is not None:
        targets = [entry.get("tp1_opposite_local_zone")]

    return {
        "entry_band": {"low": low, "high": high} if low is not None or high is not None else {},
        "entry_reference": challenger.get("entry_reference"),
        "structural_invalidation": invalidation,
        "validation_level": challenger.get("validation_level"),
        "targets": targets,
        "liquidity": list(challenger.get("liquidity") or selected.get("liquidity") or []),
    }


def evaluate_runtime_decision_v404(
    sd_eval: dict[str, Any] | None,
    *,
    event_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one compact, fail-closed runtime decision from V390 + V403."""

    sd = _d(sd_eval)
    v390 = evaluate_simple_reversal(sd)
    v403 = evaluate_afiq_scanner_bridge_v403(sd, event_risk=event_risk)

    v390_state = str(v390.get("state") or "UNAVAILABLE").upper()
    v403_state = str(v403.get("state") or "UNAVAILABLE").upper()
    d390 = _v390_direction(v390)
    d403 = _direction(v403.get("direction"))

    state = "WAIT"
    direction = "WAIT"
    grade = "NONE"
    reason = "NO_CONSENSUS"

    if v403_state == "BLOCKED_EVENT":
        state = "BLOCKED_EVENT"
        reason = str(v403.get("reason") or "V403_EVENT_BLOCK")
    elif v403_state == "INVALIDATED":
        state = "INVALIDATED"
        reason = str(v403.get("reason") or "V403_INVALIDATED")
    elif v403_state == "UNAVAILABLE":
        state = "WAIT_V403_UNAVAILABLE"
        reason = str(v403.get("reason") or "V403_UNAVAILABLE_FAIL_CLOSED")
    elif d390 in _DIRECTIONAL and d403 in _DIRECTIONAL and d390 != d403:
        state = "WAIT_CONFLICT"
        reason = f"DIRECTION_CONFLICT_V390_{d390}_V403_{d403}"
    elif d390 in _DIRECTIONAL and d403 == d390:
        direction = d390
        if v390_state in _V390_READY and v403_state == "CONFIRMED":
            state = "READY_CONFIRMED"
            grade = "A"
            reason = "V390_READY_AND_V403_CONFIRMED"
        elif v390_state in _V390_READY and v403_state == "EARLY_TAKE_RISK":
            state = "READY_EARLY"
            grade = "B"
            reason = "V390_READY_AND_V403_EARLY_LIQUIDITY_VALIDATED"
        elif v403_state == "CONFIRMED":
            state = "WATCH_CONFIRMATION"
            grade = "B"
            reason = "V403_CONFIRMED_V390_NOT_READY"
        elif v403_state == "EARLY_TAKE_RISK":
            state = "WATCH_EARLY"
            grade = "C"
            reason = "V403_EARLY_V390_NOT_READY"
        elif v390_state in _V390_READY:
            state = "WATCH_QUALITY_GATE"
            grade = "C"
            reason = f"V390_READY_V403_{v403_state}"
        else:
            state = "WATCH_ZONE"
            grade = "C"
            reason = f"ALIGNED_DIRECTION_NOT_READY_V390_{v390_state}_V403_{v403_state}"
    elif d403 in _DIRECTIONAL:
        direction = d403
        state = "WATCH_CHALLENGER_ONLY"
        grade = "C"
        reason = "V403_DIRECTION_WITHOUT_V390_ALIGNMENT"
    elif d390 in _DIRECTIONAL:
        direction = d390
        state = "WATCH_V390_ONLY"
        grade = "C"
        reason = "V390_DIRECTION_WITHOUT_V403_DIRECTION"

    geometry = _geometry(v390, v403)
    ready_for_research_candidate = state in {"READY_CONFIRMED", "READY_EARLY"}

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": state,
        "direction": direction,
        "grade": grade,
        "reason": reason,
        "price_now": v403.get("price_now") if v403.get("price_now") is not None else v390.get("price_now"),
        **geometry,
        "v390_state": v390_state,
        "v390_direction": d390,
        "v403_state": v403_state,
        "v403_direction": d403,
        "v403_reason": v403.get("reason"),
        "rr_first_target": v403.get("rr_first_target"),
        "event": _d(v403.get("event")),
        "paths": _d(v403.get("paths")),
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "research_candidate": ready_for_research_candidate,
        "research_promotion_required": True,
        "required_research_gates": dict(RESEARCH_GATES),
        "validation_status": "V404_SHADOW_CONSENSUS_RESEARCH_REQUIRED_BEFORE_DEMO_PROMOTION",
        "components": {
            "v390": v390,
            "v403": v403,
        },
    }

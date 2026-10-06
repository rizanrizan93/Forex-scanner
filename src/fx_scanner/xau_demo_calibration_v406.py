from __future__ import annotations

"""V406 selector for forward DEMO calibration candidates.

V406 does not talk to a broker.  It promotes *research candidates* from the
V404 consensus layer and the V405 tier map into a compact, auditable DEMO
calibration contract that a separate DEMO-only sampler may consume.

The purpose is to collect forward entry/outcome evidence without granting LIVE
execution authority or converting every mapped zone into a trade.
"""

from math import isfinite
from typing import Any

from .xau_runtime_decision_v404 import evaluate_runtime_decision_v404
from .xau_whalezone_reconstruction_v405 import evaluate_whalezone_reconstruction_v405

CONTRACT = "XAU_RIZAN_DEMO_CALIBRATION_SELECTOR_V406"
MODE = "DEMO_CALIBRATION_SELECTION"

HARD_BLOCK_STATES = {
    "BLOCKED_EVENT",
    "INVALIDATED",
    "WAIT_CONFLICT",
    "WAIT_V403_UNAVAILABLE",
    "UNAVAILABLE",
}


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _direction(value: Any) -> str:
    raw = str(value or "WAIT").upper()
    return raw if raw in {"LONG", "SHORT"} else "WAIT"


def _geometry_complete(v404: dict[str, Any]) -> tuple[bool, str]:
    direction = _direction(v404.get("direction"))
    band = _d(v404.get("entry_band"))
    low = _f(band.get("low"))
    high = _f(band.get("high"))
    stop = _f(v404.get("structural_invalidation"))
    targets = [_f(value) for value in list(v404.get("targets") or [])]
    targets = [value for value in targets if value is not None]
    if direction == "WAIT":
        return False, "DIRECTION_WAIT"
    if low is None or high is None or high <= low:
        return False, "ENTRY_BAND_INVALID"
    if stop is None:
        return False, "STRUCTURAL_INVALIDATION_MISSING"
    if not targets:
        return False, "STRUCTURAL_TARGET_MISSING"
    mid = (low + high) / 2.0
    if direction == "LONG":
        if stop >= mid:
            return False, "LONG_STOP_NOT_BELOW_ENTRY"
        if not any(target > mid for target in targets):
            return False, "LONG_TARGET_NOT_ABOVE_ENTRY"
    else:
        if stop <= mid:
            return False, "SHORT_STOP_NOT_ABOVE_ENTRY"
        if not any(target < mid for target in targets):
            return False, "SHORT_TARGET_NOT_BELOW_ENTRY"
    return True, "GEOMETRY_COMPLETE"


def _v405_alignment(v405: dict[str, Any], direction: str) -> tuple[str, str]:
    focus = _direction(v405.get("direction"))
    if focus == direction:
        return "ALIGNED", str(v405.get("reason") or "V405_SAME_DIRECTION")
    if focus == "WAIT":
        return "NEUTRAL", str(v405.get("reason") or "V405_MAP_ONLY")
    return "CONFLICT", f"V405_{focus}_VS_V404_{direction}"


def _cohort(v404: dict[str, Any], v405: dict[str, Any]) -> tuple[str, str]:
    state = str(v404.get("state") or "UNAVAILABLE").upper()
    grade = str(v404.get("grade") or "NONE").upper()
    direction = _direction(v404.get("direction"))
    alignment, alignment_reason = _v405_alignment(v405, direction)

    if state in HARD_BLOCK_STATES:
        return "NONE", f"HARD_BLOCK:{state}"
    if direction == "WAIT":
        return "NONE", "V404_DIRECTION_WAIT"
    if state == "READY_CONFIRMED" and grade == "A":
        if alignment == "CONFLICT":
            return "NONE", alignment_reason
        return "A", "V404_GRADE_A_V405_NOT_CONFLICTING"
    if state == "READY_EARLY" and grade == "B":
        if alignment != "ALIGNED":
            return "NONE", f"GRADE_B_REQUIRES_V405_ALIGNMENT:{alignment_reason}"
        return "B", "V404_GRADE_B_V405_ALIGNED"

    # Experimental forward sample: only when V404 has a directional WATCH state
    # and V405 independently focuses the same side.  This cohort is kept
    # separate from A/B so its lower-quality evidence cannot inflate promotion
    # statistics.
    if state.startswith("WATCH") and alignment == "ALIGNED":
        if str(v405.get("state") or "").upper() in {"FOCUS_BUY_1", "FOCUS_SELL_1"}:
            return "C", "V404_WATCH_PLUS_V405_ACTIVE_EDGE"
    return "NONE", f"NOT_CALIBRATION_ELIGIBLE:{state}:{alignment}"


def build_demo_calibration_candidate_v406(
    v404: dict[str, Any] | None,
    v405: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one non-broker calibration contract from precomputed decisions."""
    decision = _d(v404)
    tiers = _d(v405)
    state = str(decision.get("state") or "UNAVAILABLE").upper()
    direction = _direction(decision.get("direction"))
    cohort, reason = _cohort(decision, tiers)
    geometry_ok, geometry_reason = _geometry_complete(decision)

    eligible = cohort in {"A", "B", "C"} and geometry_ok
    if cohort != "NONE" and not geometry_ok:
        reason = geometry_reason

    band = _d(decision.get("entry_band"))
    targets = [value for value in list(decision.get("targets") or []) if _f(value) is not None]
    whale_alignment, whale_reason = _v405_alignment(tiers, direction)

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": "DEMO_CALIBRATION_ELIGIBLE" if eligible else "WAIT",
        "eligible": eligible,
        "cohort": cohort if eligible else "NONE",
        "direction": direction if eligible else "WAIT",
        "reason": reason,
        "source_v404_state": state,
        "source_v404_grade": decision.get("grade"),
        "source_v405_state": tiers.get("state"),
        "v405_alignment": whale_alignment,
        "v405_alignment_reason": whale_reason,
        "entry_band": {
            "low": _f(band.get("low")),
            "high": _f(band.get("high")),
        },
        "entry_reference": _f(decision.get("entry_reference")),
        "structural_invalidation": _f(decision.get("structural_invalidation")),
        "targets": [_f(value) for value in targets],
        "rr_first_target": _f(decision.get("rr_first_target")),
        "liquidity": list(decision.get("liquidity") or []),
        "event": _d(decision.get("event")),
        "calibration_policy": {
            "lot": 0.01,
            "one_order_per_signature": True,
            "one_open_or_pending_v406_max": True,
            "structural_sl_required": True,
            "structural_tp_required": True,
            "minimum_rr": 1.0,
            "no_chase": True,
            "cohorts_kept_separate": True,
        },
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "validation_status": (
            "V406_DEMO_CALIBRATION_CANDIDATE_READY_FOR_DEMO_ONLY_SAMPLER"
            if eligible
            else "V406_WAIT_FOR_ELIGIBLE_FORWARD_SAMPLE"
        ),
    }


def evaluate_demo_calibration_v406(
    sd_eval: dict[str, Any] | None,
    *,
    event_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate V404 and V405 on the same causal snapshot, then select a cohort."""
    sd = _d(sd_eval)
    v404 = evaluate_runtime_decision_v404(sd, event_risk=event_risk)
    v405 = evaluate_whalezone_reconstruction_v405(sd)
    out = build_demo_calibration_candidate_v406(v404, v405)
    return {
        **out,
        "components": {
            "v404": v404,
            "v405": v405,
        },
    }


__all__ = [
    "CONTRACT",
    "MODE",
    "build_demo_calibration_candidate_v406",
    "evaluate_demo_calibration_v406",
]

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

DOM_WORKER = "ctrader_demo_xau_dom_v191"
MAX_DOM_AGE_SECONDS = 150.0
MIN_TRANSITION_DELTA = 2.0
STRONG_TRANSITION_DELTA = 4.0


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


def evaluate_pressure_transition(
    *,
    direction: str,
    dom_heartbeat: dict[str, Any],
    now: datetime,
    max_age_seconds: float = MAX_DOM_AGE_SECONDS,
) -> dict[str, Any]:
    """Classify cTrader Level-II pressure transition for DEMO entry timing.

    V191 pressure score is 0..100 where lower values are ASK/seller dominant
    and higher values are BID/buyer dominant. Positive opposing_pressure means
    the incoming move is still pushing deeper into the S/D zone.

    Broker execution fails closed when DOM is missing, unhealthy, stale, or
    has no comparable previous sample.
    """
    side = str(direction or "").upper()
    observed_at = _dt(dom_heartbeat.get("observed_at"))
    healthy = bool(dom_heartbeat.get("healthy"))
    details = dict(dom_heartbeat.get("details") or {})
    analysis = dict(details.get("analysis") or {})
    score = _f(analysis.get("dom_pressure_score"))
    cross = dict(analysis.get("cross_run") or {})
    delta = _f(cross.get("pressure_score_change"))
    imbalance = _f(analysis.get("last_imbalance"))

    age_seconds = None
    if observed_at is not None:
        age_seconds = max(0.0, (now.astimezone(UTC) - observed_at).total_seconds())

    base = {
        "direction": side,
        "dom_state": str(analysis.get("state") or "UNAVAILABLE"),
        "score": score,
        "buyer_index": score,
        "seller_index": None if score is None else 100.0 - score,
        "score_change": delta,
        "last_imbalance": imbalance,
        "observed_at": None if observed_at is None else observed_at.isoformat(),
        "age_seconds": age_seconds,
        "fresh": False,
        "opposing_pressure": None,
        "transition_toward_confirmation": None,
        "state": "UNAVAILABLE",
        "pre_touch_entry_allowed": False,
        "confirmation_entry_allowed": False,
        "hard_block": True,
        "reason": "DOM_UNAVAILABLE",
    }
    if side not in {"LONG", "SHORT"}:
        return {**base, "state": "NO_DIRECTION", "reason": "NO_CANONICAL_DIRECTION"}
    if not healthy:
        return {**base, "state": "DOM_UNHEALTHY", "reason": "DOM_HEARTBEAT_UNHEALTHY"}
    if observed_at is None or age_seconds is None or age_seconds > float(max_age_seconds):
        return {**base, "state": "DOM_STALE", "reason": "DOM_PRESSURE_STALE"}
    if score is None:
        return {**base, "state": "DOM_SCORE_MISSING", "reason": "DOM_SCORE_MISSING"}
    if delta is None:
        return {**base, "state": "WAIT_SECOND_SAMPLE", "reason": "PRESSURE_DELTA_MISSING"}

    signed_buyer = max(-100.0, min(100.0, (score - 50.0) * 2.0))
    opposing = -signed_buyer if side == "LONG" else signed_buyer
    toward = delta if side == "LONG" else -delta

    state = "CONTESTED"
    pre_touch = False
    confirm = False
    hard_block = False
    reason = "PRESSURE_TRANSITION_NOT_READY"

    if opposing >= 45.0:
        if toward >= STRONG_TRANSITION_DELTA:
            state = "OPPOSING_FADING_EARLY"
            confirm = True
            reason = "STRONG_OPPOSING_PRESSURE_FADING_M5_REQUIRED"
        else:
            state = "OPPOSING_REACCELERATION"
            hard_block = True
            reason = "INCOMING_PRESSURE_STILL_STRONG"
    elif opposing >= 15.0:
        if toward >= STRONG_TRANSITION_DELTA:
            state = "OPPOSING_FADING"
            pre_touch = opposing <= 25.0
            confirm = True
            reason = (
                "PRESSURE_FADING_PRETOUCH_ALLOWED"
                if pre_touch
                else "PRESSURE_FADING_M5_CONFIRMATION_ALLOWED"
            )
        elif toward >= MIN_TRANSITION_DELTA:
            state = "FADING_EARLY"
            confirm = True
            reason = "EARLY_FADE_M5_CONFIRMATION_REQUIRED"
        else:
            state = "OPPOSING_STILL_ACTIVE"
            reason = "WAIT_PRESSURE_FADE"
    elif opposing > -15.0:
        state = "BALANCED_ABSORPTION"
        pre_touch = toward >= 0.0
        confirm = True
        reason = (
            "BALANCED_ABSORPTION_READY"
            if pre_touch
            else "BALANCED_BUT_TRANSITION_NOT_IMPROVING"
        )
    else:
        state = "CONTROL_FLIP"
        pre_touch = True
        confirm = True
        reason = "COUNTER_PRESSURE_HAS_TAKEN_CONTROL"

    return {
        **base,
        "fresh": True,
        "opposing_pressure": opposing,
        "transition_toward_confirmation": toward,
        "state": state,
        "pre_touch_entry_allowed": bool(pre_touch and not hard_block),
        "confirmation_entry_allowed": bool(confirm and not hard_block),
        "hard_block": bool(hard_block),
        "reason": reason,
    }
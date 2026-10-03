from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from math import isfinite
from typing import Any

from . import demo_xau_v351_executor as base
from .xau_reaction_interceptor_v374 import evaluate_reaction_interceptor

EXECUTOR_CONTRACT = "XAU_RIZAN_DEMO_REACTION_EXECUTOR_V375_2_AFIQ_BEHAVIOR_V376"
EXECUTION_LANE_REACTION = "V374_REACTION_INTERCEPTOR"
EXECUTION_LANE_STANDARD = "V342_MICRO_CONFIRMATION"
REACTION_ENTRY_MODE = "REACTION_EARLY_DEMO_PROBE"
REACTION_CONFIRMATION_TIER = "REACTION_EARLY"
EVENT_TYPE = "DEMO_XAU_V375_REACTION_EXECUTION"

_BASE_CANDIDATE = base._candidate
_BASE_EVIDENCE_LEDGER = base._evidence_ledger


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if out.tzinfo is None:
        return None
    return out.astimezone(UTC)


def _behavioral_block_reason(heartbeat: dict[str, Any]) -> str | None:
    evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
    behavior = dict(evaluation.get("afiq_behavioral") or {})
    gate = str(behavior.get("demo_entry_gate") or "ALLOW_WITH_EXISTING_GATES").upper()
    if gate.startswith("BLOCK_"):
        reason = str(behavior.get("hard_block_reason") or gate)
        return f"AFIQ_BEHAVIOR_BLOCK:{reason}"
    return None


def _reaction_signal_id(evaluation: dict[str, Any], reaction: dict[str, Any]) -> str:
    candidate = dict(reaction.get("candidate") or {})
    destination = dict(evaluation.get("structural_destination") or {})
    raw = "|".join(
        [
            str(evaluation.get("expected_reversal_direction") or "WAIT"),
            str(candidate.get("center") or "NO_CENTER"),
            str(candidate.get("lifecycle_state") or "NO_LIFECYCLE"),
            str(candidate.get("low") or "NO_LOW"),
            str(candidate.get("high") or "NO_HIGH"),
            str(destination.get("zone_id") or destination.get("price") or "NO_DESTINATION"),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"XAU_V375_RX_{digest}"


def _reaction_candidate(
    *,
    heartbeat: dict[str, Any],
    bid: float,
    ask: float,
    now: datetime,
) -> tuple[dict[str, Any] | None, str]:
    """Admit a V374 early reaction only to the DEMO executor.

    The lane deliberately relaxes the *full MSS first* requirement, but it does
    not relax source freshness, V342 DEMO authority, event blackout, structural
    room, roadblock room, structural SL/TP geometry, minimum RR, no-chase, or
    a V376 causal behavioral-failure block.
    """
    if not heartbeat or not bool(heartbeat.get("healthy")):
        return None, "SOURCE_HEARTBEAT_UNHEALTHY"

    observed_at = _dt(heartbeat.get("observed_at"))
    if observed_at is None:
        return None, "SOURCE_TIME_INVALID"
    age = (now - observed_at).total_seconds()
    if age < -1.0 or age > base.MAX_SOURCE_AGE_SECONDS:
        return None, f"SOURCE_STALE:{age:.1f}s"

    evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
    contract = str(evaluation.get("contract") or "")
    if not contract.startswith(base.ENGINE_CONTRACT_PREFIX):
        return None, "ENGINE_CONTRACT_MISMATCH"
    if not bool(evaluation.get("execution_authority")):
        return None, "ENGINE_DEMO_EXECUTION_NOT_AUTHORIZED"
    if bool(evaluation.get("live_execution_enabled")):
        return None, "LIVE_EXECUTION_FLAG_FORBIDDEN"

    direction = str(evaluation.get("expected_reversal_direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None, "DIRECTION_INVALID"

    structural_room = dict(evaluation.get("structural_room") or {})
    roadblock_room = dict(evaluation.get("roadblock_room") or {})
    news = dict(evaluation.get("news_zone") or {})
    destination = dict(evaluation.get("structural_destination") or {})
    roadblock = dict(evaluation.get("nearest_roadblock") or {})

    if bool(structural_room.get("blocked")):
        return None, f"STRUCTURAL_ROOM_BLOCK:{structural_room.get('state') or 'BLOCK'}"
    if bool(roadblock_room.get("blocked")):
        return None, f"ROADBLOCK_ROOM_BLOCK:{roadblock_room.get('state') or 'BLOCK'}"

    execution_risk = str(
        news.get("execution_risk_state") or news.get("risk_state") or "CLEAR"
    ).upper()
    effective_news = str(news.get("effective_entry_state") or "WAIT_CONFIRMATION").upper()
    hard_news_states = {"PRE_EVENT", "EVENT_WINDOW", "NEWS_SOURCE_UNAVAILABLE"}
    if execution_risk in hard_news_states:
        return None, f"NEWS_RISK_BLOCK:{execution_risk}"
    if (
        effective_news.startswith("WAIT_FOR_NEWS")
        or effective_news.startswith("WAIT_NEWS")
        or effective_news.startswith("WAIT_POST_NEWS")
        or effective_news.startswith("BLOCK_")
    ):
        return None, f"NEWS_GATE:{effective_news}"

    reaction = evaluate_reaction_interceptor(
        evaluation,
        direction=direction,
        context_alignment="UNAVAILABLE",
    )
    state = str(reaction.get("state") or "NONE").upper()
    required_state = f"EARLY_REACTION_{direction}"
    if state == "MISSED_NO_CHASE" or bool(reaction.get("no_chase")):
        return None, "REACTION_MOVE_MISSED_NO_CHASE"
    if not bool(reaction.get("promoted")) or state != required_state:
        return None, f"REACTION_GATE:{state}"

    band = dict(reaction.get("early_entry_band") or {})
    entry_low = _f(band.get("low"))
    entry_high = _f(band.get("high"))
    stop_loss = _f(reaction.get("invalidation"))
    if (
        entry_low is None
        or entry_high is None
        or stop_loss is None
        or entry_low <= 0
        or entry_high <= entry_low
        or stop_loss <= 0
    ):
        return None, "REACTION_GEOMETRY_INVALID"

    executable = float(ask if direction == "LONG" else bid)
    if not (entry_low <= executable <= entry_high):
        return None, "REACTION_QUOTE_OUTSIDE_EARLY_BAND_NO_CHASE"

    target = None
    target_source = None
    rb_target = _f(roadblock.get("near_edge"))
    if rb_target is not None:
        target = rb_target
        target_source = "NEAREST_ROADBLOCK"
    else:
        target = _f(destination.get("price"))
        target_source = "H4_DESTINATION"
    if target is None or target <= 0:
        return None, "STRUCTURAL_TARGET_MISSING"

    if direction == "LONG":
        if not (stop_loss < executable < target):
            return None, "LONG_SLTP_GEOMETRY_INVALID"
        risk = executable - stop_loss
        reward = target - executable
    else:
        if not (target < executable < stop_loss):
            return None, "SHORT_SLTP_GEOMETRY_INVALID"
        risk = stop_loss - executable
        reward = executable - target
    if risk <= 0 or reward <= 0:
        return None, "RISK_REWARD_GEOMETRY_INVALID"

    rr = reward / risk
    if rr + 1e-9 < base.MIN_RR:
        return None, f"RR_BELOW_{base.MIN_RR:.2f}:{rr:.3f}"

    main_zone = dict(evaluation.get("main_reversal_zone") or {})
    reaction_candidate = dict(reaction.get("candidate") or {})
    signal_id = _reaction_signal_id(evaluation, reaction)
    return {
        "signal_id": signal_id,
        "direction": direction,
        "entry": executable,
        "entry_mode": REACTION_ENTRY_MODE,
        "confirmation_tier": REACTION_CONFIRMATION_TIER,
        "execution_lane": EXECUTION_LANE_REACTION,
        "executor_contract": EXECUTOR_CONTRACT,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "confirmation_age_seconds": None,
        "confirmation_drift_atr": None,
        "stop_loss": stop_loss,
        "take_profit": target,
        "target_source": target_source,
        "rr": rr,
        "observed_at": observed_at,
        "parent_zone_id": main_zone.get("zone_id"),
        "destination_zone_id": destination.get("zone_id"),
        "reclaim_at": None,
        "reaction_interceptor": reaction,
        "reaction_center": reaction_candidate.get("center"),
        "reaction_lifecycle_state": reaction_candidate.get("lifecycle_state"),
        "reaction_score": reaction_candidate.get("score"),
        "main_zone_role": reaction.get("main_zone_role"),
    }, "ELIGIBLE_REACTION_DEMO"


def _candidate(
    *,
    heartbeat: dict[str, Any],
    bid: float,
    ask: float,
    now: datetime,
) -> tuple[dict[str, Any] | None, str]:
    """Prefer V342 confirmation, then V374 reaction, with V376 failure veto."""
    behavior_block = _behavioral_block_reason(heartbeat)
    if behavior_block:
        return None, behavior_block

    standard, standard_reason = _BASE_CANDIDATE(
        heartbeat=heartbeat,
        bid=bid,
        ask=ask,
        now=now,
    )
    if standard is not None:
        standard = dict(standard)
        standard["execution_lane"] = EXECUTION_LANE_STANDARD
        standard["executor_contract"] = EXECUTOR_CONTRACT
        return standard, standard_reason

    reaction, reaction_reason = _reaction_candidate(
        heartbeat=heartbeat,
        bid=bid,
        ask=ask,
        now=now,
    )
    if reaction is not None:
        return reaction, reaction_reason

    foundational_prefixes = (
        "SOURCE_",
        "ENGINE_",
        "LIVE_EXECUTION_",
        "STRUCTURAL_ROOM_BLOCK:",
        "ROADBLOCK_ROOM_BLOCK:",
        "NEWS_",
        "AFIQ_BEHAVIOR_BLOCK:",
    )
    if standard_reason.startswith(foundational_prefixes):
        return None, standard_reason
    return None, reaction_reason


def _evidence_ledger(
    heartbeat: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    ledger = dict(_BASE_EVIDENCE_LEDGER(heartbeat, candidate))
    evaluation = dict(dict(heartbeat.get("details") or {}).get("evaluation") or {})
    behavior = dict(evaluation.get("afiq_behavioral") or {})
    ledger["schema"] = "XAU_RIZAN_DEMO_EVIDENCE_LEDGER_V376_1"
    ledger["executor_contract"] = EXECUTOR_CONTRACT
    ledger["execution_lane"] = candidate.get("execution_lane")
    ledger["reaction_interceptor"] = dict(candidate.get("reaction_interceptor") or {})
    ledger["afiq_behavioral"] = {
        "contract": behavior.get("contract"),
        "regime": dict(behavior.get("regime") or {}).get("state"),
        "active_zone_role": dict(behavior.get("active_zone_role") or {}).get("role"),
        "acceptance_rejection": dict(behavior.get("acceptance_rejection") or {}).get("state"),
        "m30_internal": dict(behavior.get("m30_internal") or {}).get("state"),
        "response_timer": dict(behavior.get("response_timer") or {}).get("state"),
        "manual_decision_state": behavior.get("manual_decision_state"),
        "demo_entry_gate": behavior.get("demo_entry_gate"),
        "hard_block_reason": behavior.get("hard_block_reason"),
    }
    order_plan = dict(ledger.get("order_plan") or {})
    order_plan.update(
        {
            "entry_mode": candidate.get("entry_mode"),
            "confirmation_tier": candidate.get("confirmation_tier"),
            "execution_lane": candidate.get("execution_lane"),
            "reaction_center": candidate.get("reaction_center"),
            "reaction_lifecycle_state": candidate.get("reaction_lifecycle_state"),
            "reaction_score": candidate.get("reaction_score"),
            "afiq_behavior_gate": behavior.get("demo_entry_gate"),
        }
    )
    ledger["order_plan"] = order_plan
    return ledger


def run() -> int:
    """Run the proven V351 DEMO router with V375 selector + V376 failure veto."""
    base._candidate = _candidate
    base._evidence_ledger = _evidence_ledger
    base.EVENT_TYPE = EVENT_TYPE
    return base.run()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v213_post_zone_path"
CONTRACT = "XAU_POST_ZONE_PATH_V213"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
PROBABILITY_WORKER = "ctrader_demo_xau_v212_zone_reaction_probability"
EVIDENCE_WORKER = "ctrader_demo_xau_v198_evidence_analytics"


def _latest_heartbeat(store: SupabaseOperationalStore, worker_name: str) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _stage(leg: dict[str, Any]) -> str:
    pocket_state = str(leg.get("pocket_state") or "").upper()
    micro = dict(leg.get("micro_refinement") or {})
    micro_state = str(micro.get("state") or "").upper()

    if "INVALIDATED" in pocket_state or "INVALIDATED" in micro_state:
        return "INVALIDATED"
    if pocket_state == "REFINED_M5_POCKET":
        return "REFINED_REACTION_ACTIVE"
    if micro_state == "M5_MSS_WAIT_DISPLACEMENT":
        return "MSS_WAIT_DISPLACEMENT"
    if micro_state == "M5_RECLAIM_WAIT_MSS":
        return "RECLAIMED_WAIT_MSS"
    if micro_state == "M5_TOUCH_WAIT_RECLAIM":
        return "TOUCHED_WAIT_RECLAIM"
    if pocket_state == "CANDIDATE_M5_POCKET":
        return "CANDIDATE_POCKET_ACTIVE"
    if micro_state == "WAIT_SOURCE_TOUCH":
        return "PRE_TOUCH"
    return "WAITING_FOR_M5_PATH"


def _probability_for_leg(
    leg: dict[str, Any],
    probability_details: dict[str, Any],
) -> dict[str, Any]:
    source = dict(leg.get("source_zone") or {})
    zone_id = str(source.get("zone_id") or "")
    if not zone_id:
        return {}

    for row in list(probability_details.get("zone_probabilities") or []):
        item = dict(row)
        if str(item.get("zone_id") or "") == zone_id:
            return item
    return {}


def _target_payload(leg: dict[str, Any]) -> dict[str, Any]:
    target = dict(leg.get("reaction_target") or {})
    terminal = dict(leg.get("terminal_target_zone") or {})
    checkpoints = [
        dict(item)
        for item in list(leg.get("target_ladder") or [])
        if str(dict(item).get("role") or "").upper() == "CHECKPOINT"
    ]
    return {
        "reaction_target": target,
        "checkpoint_targets": checkpoints,
        "terminal_target_zone": terminal,
    }


def _leg_payload(
    leg: dict[str, Any],
    probability_details: dict[str, Any],
) -> dict[str, Any]:
    probability = _probability_for_leg(leg, probability_details)
    reaction = dict(probability.get("reaction") or {})
    destination = dict(probability.get("destination") or {})
    median_bars = reaction.get("median_bars_to_outcome")
    try:
        expected_minutes = None if median_bars is None else float(median_bars) * 5.0
    except (TypeError, ValueError):
        expected_minutes = None

    return {
        "direction": leg.get("direction"),
        "stage": _stage(leg),
        "pocket_state": leg.get("pocket_state"),
        "m5_pocket": dict(leg.get("m5_pocket") or {}),
        "source_zone": dict(leg.get("source_zone") or {}),
        **_target_payload(leg),
        "historical_estimate": {
            "p_touch": destination.get("p_touch"),
            "p_hold_025": reaction.get("p_hold_025"),
            "p_hold_050": reaction.get("p_hold_050"),
            "p_hold_075": reaction.get("p_hold_075"),
            "p_hold_100": reaction.get("p_hold_100"),
            "p_break": reaction.get("p_break"),
            "p_stall": reaction.get("p_stall"),
            "p_075_given_050": reaction.get("p_075_given_050"),
            "p_100_given_050": reaction.get("p_100_given_050"),
            "median_mfe_atr": reaction.get("median_mfe_atr"),
            "median_mae_atr": reaction.get("median_mae_atr"),
            "p75_mae_atr": reaction.get("p75_mae_atr"),
            "median_bars_to_outcome": median_bars,
            "median_minutes_to_outcome": expected_minutes,
            "confidence": reaction.get("confidence"),
            "matched_contracts": reaction.get("matched_contracts"),
            "estimate_type": reaction.get("estimate_type"),
        },
    }


def _dominant_outcome(estimate: dict[str, Any]) -> str:
    values: list[tuple[str, float]] = []
    for label, key in (
        ("HOLD_0_50", "p_hold_050"),
        ("BREAK", "p_break"),
        ("STALL", "p_stall"),
    ):
        try:
            value = float(estimate.get(key))
        except (TypeError, ValueError):
            continue
        values.append((label, value))
    if not values:
        return "INSUFFICIENT_EVIDENCE"
    values.sort(key=lambda item: item[1], reverse=True)
    return values[0][0]


def evaluate_post_zone_path(
    projection: dict[str, Any],
    probability_details: dict[str, Any],
    evidence_details: dict[str, Any],
) -> dict[str, Any]:
    current = _leg_payload(dict(projection.get("current_leg") or {}), probability_details)
    next_leg = _leg_payload(dict(projection.get("next_leg") or {}), probability_details)

    current_estimate = dict(current.get("historical_estimate") or {})
    current["dominant_historical_outcome"] = _dominant_outcome(current_estimate)
    current["after_0_50_atr"] = {
        "p_extend_to_0_75": current_estimate.get("p_075_given_050"),
        "p_extend_to_1_00": current_estimate.get("p_100_given_050"),
        "interpretation": (
            "Conditional continuation estimate after a 0.50 ATR reaction; historical shadow "
            "estimate only, not a guaranteed path."
        ),
    }

    all_evidence = dict(evidence_details.get("all_evidence") or {})
    full_path = dict(evidence_details.get("strict_full_path") or evidence_details.get("full_path") or {})

    return {
        "contract": CONTRACT,
        "state": "POST_ZONE_PATH_AVAILABLE" if current.get("direction") else "NO_ACTIVE_PATH",
        "current_leg": current,
        "next_leg": next_leg,
        "prospective_v197_v198_overlay": {
            "enrolled": all_evidence.get("enrolled"),
            "touched": all_evidence.get("touched"),
            "resolved_after_touch": all_evidence.get("resolved_after_touch"),
            "reaction_precision_given_touch": all_evidence.get("reaction_precision_given_touch"),
            "terminal_precision_given_touch": all_evidence.get("terminal_precision_given_touch"),
            "reaction_wilson_lower_95": all_evidence.get("reaction_wilson_lower_95"),
            "terminal_wilson_lower_95": all_evidence.get("terminal_wilson_lower_95"),
            "median_touch_to_reaction_minutes": all_evidence.get("median_touch_to_reaction_minutes"),
            "median_touch_to_terminal_minutes": all_evidence.get("median_touch_to_terminal_minutes"),
            "full_path_max_stage_score": full_path.get("max_stage_score"),
            "full_path_stage_reached_counts": dict(full_path.get("stage_reached_counts") or {}),
        },
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V213 describes the post-zone state machine and expected reaction/continuation path. "
            "It cannot create or block an order. Current probabilities come from V212 historical "
            "cohorts and are cross-checked against V197/V198 prospective evidence."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V213_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V213_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    evaluation: dict[str, Any] = {}

    try:
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        probability_hb = _latest_heartbeat(store, PROBABILITY_WORKER)
        evidence_hb = _latest_heartbeat(store, EVIDENCE_WORKER)

        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        projection = dict(atlas_eval.get("m5_path_projection") or {})
        probability_details = dict(probability_hb.get("details") or {})
        evidence_details = dict(evidence_hb.get("details") or {})
        evaluation = evaluate_post_zone_path(
            projection,
            probability_details,
            evidence_details,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "evaluation": evaluation,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "observed_at": now.isoformat(),
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V213_POST_ZONE_PATH "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

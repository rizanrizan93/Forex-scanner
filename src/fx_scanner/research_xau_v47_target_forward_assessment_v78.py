from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from math import inf
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import ensure_utc
from .research_xau_v47_forward_observer_v70 import (
    EVENT_TYPE as EVALUATION_EVENT,
    RESEARCH_VERSION as V70_RESEARCH_VERSION,
)
from .research_xau_v47_forward_outcomes_v71 import (
    OUTCOME_EVENT,
    RESEARCH_VERSION as V71_RESEARCH_VERSION,
    summarize_outcomes,
)
from .research_xau_v47_target_forward_freeze_v77 import (
    ARTIFACT_CONTRACT as FREEZE_ARTIFACT_CONTRACT,
    FORWARD_CONTRACT,
    PROSPECTIVE_EPOCH,
    assess_forward_snapshot,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
RESEARCH_VERSION = "XAU_V47_TARGET_FORWARD_ASSESSMENT_V78"
ARTIFACT_CONTRACT = "XAU_V47_TARGET_FORWARD_ASSESSMENT_V78_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False
WORKER_NAME = "xau_v47_target_forward_assessment_v78"

PRIMARY_GROUP = "TARGET_GT_0_75"
REFERENCE_GROUP = "TARGET_LE_0_75"


def _dt(value: Any) -> datetime:
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _effective_pf(metrics: Mapping[str, Any]) -> float | None:
    if bool(metrics.get("profit_factor_infinite")):
        return inf
    value = metrics.get("profit_factor")
    return None if value is None else float(value)


def evaluate_target_forward(
    evaluations: Mapping[str, Mapping[str, Any]],
    outcomes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    primary_rows: list[dict[str, Any]] = []
    reference_rows: list[dict[str, Any]] = []
    eligible_evaluations = 0
    unresolved = 0
    excluded_before_epoch = 0
    unavailable_geometry = 0

    for signal_key, evaluation in sorted(
        evaluations.items(),
        key=lambda item: str(item[1].get("signal_at") or ""),
    ):
        signal_at_raw = evaluation.get("signal_at")
        if not signal_at_raw:
            continue
        if _dt(signal_at_raw) < PROSPECTIVE_EPOCH:
            excluded_before_epoch += 1
            continue
        if not bool(evaluation.get("v47_approved")):
            continue

        target_context = dict(evaluation.get("target_credibility") or {})
        group = str(target_context.get("target_forward_group") or "")
        if group not in {PRIMARY_GROUP, REFERENCE_GROUP}:
            unavailable_geometry += 1
            continue

        eligible_evaluations += 1
        outcome = outcomes.get(signal_key)
        if outcome is None:
            unresolved += 1
            continue

        joined = {
            **dict(outcome),
            "signal_key": signal_key,
            "target_forward_group": group,
            "target_to_prior60_d1_median": target_context.get(
                "target_to_prior60_d1_median"
            ),
        }
        if group == PRIMARY_GROUP:
            primary_rows.append(joined)
        else:
            reference_rows.append(joined)

    primary = summarize_outcomes(primary_rows)
    reference = summarize_outcomes(reference_rows)
    assessment = assess_forward_snapshot(
        primary_closed_trades=int(primary["closed_trades"]),
        reference_closed_trades=int(reference["closed_trades"]),
        primary_profit_factor=_effective_pf(primary),
        reference_profit_factor=_effective_pf(reference),
        primary_expectancy_r=primary["expectancy_r"],
        reference_expectancy_r=reference["expectancy_r"],
        primary_net_r=float(primary["net_r"]),
        primary_max_drawdown_r=float(primary["max_drawdown_r"]),
        reference_max_drawdown_r=float(reference["max_drawdown_r"]),
    )
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "freeze_artifact_contract": FREEZE_ARTIFACT_CONTRACT,
        "forward_contract": FORWARD_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "prospective_epoch": PROSPECTIVE_EPOCH.isoformat(),
        "primary_group": PRIMARY_GROUP,
        "reference_group": REFERENCE_GROUP,
        "counts": {
            "evaluations_total": len(evaluations),
            "outcomes_total": len(outcomes),
            "eligible_evaluations": eligible_evaluations,
            "unresolved": unresolved,
            "excluded_before_epoch": excluded_before_epoch,
            "unavailable_geometry": unavailable_geometry,
        },
        "primary_target_gt_0_75": primary,
        "reference_target_le_0_75": reference,
        "assessment": assessment,
        "note": (
            "V78 joins immutable V70 prospective evaluation events to immutable V71 "
            "paper outcomes by signal_key. It does not change V69 SWEEP/NON_SWEEP "
            "classification, V71 outcome simulation, entry, stop, target, or execution."
        ),
    }


def _evaluation_rows(store: Any) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,observed_at,payload")
        .eq("event_type", EVALUATION_EVENT)
        .eq("code", V70_RESEARCH_VERSION)
        .order("observed_at", desc=False)
        .limit(5000)
        .execute()
    )
    return {
        str(row["signal_key"]): dict(row.get("payload") or {})
        for row in (response.data or [])
        if row.get("signal_key")
    }


def _outcome_rows(store: Any) -> dict[str, dict[str, Any]]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key,observed_at,payload")
        .eq("event_type", OUTCOME_EVENT)
        .eq("code", V71_RESEARCH_VERSION)
        .order("observed_at", desc=False)
        .limit(5000)
        .execute()
    )
    return {
        str(row["signal_key"]): dict(row.get("payload") or {})
        for row in (response.data or [])
        if row.get("signal_key")
    }


def run() -> int:
    store = SupabaseOperationalStore.from_env()
    evaluations = _evaluation_rows(store)
    outcomes = _outcome_rows(store)
    result = evaluate_target_forward(evaluations, outcomes)
    result["observed_at"] = datetime.now(tz=UTC).isoformat()
    result["storage_table"] = "broker_order_events"
    result["source_evaluation_event"] = EVALUATION_EVENT
    result["source_outcome_event"] = OUTCOME_EVENT

    store.write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=result,
    )

    path = Path(
        os.getenv(
            "V78_EVIDENCE_OUTPUT",
            "artifacts/xau-v47-target-forward-assessment-v78.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": result,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n"
    )

    primary = result["primary_target_gt_0_75"]
    reference = result["reference_target_le_0_75"]
    assessment = result["assessment"]
    print(
        "V78_TARGET_FORWARD "
        f"eligible={result['counts']['eligible_evaluations']} "
        f"unresolved={result['counts']['unresolved']} "
        f"primary_n={primary['closed_trades']} reference_n={reference['closed_trades']} "
        f"decision={assessment['decision']} artifact={path} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

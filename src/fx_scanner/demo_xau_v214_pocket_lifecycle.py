from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
import os
from typing import Any, Sequence

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v214_pocket_lifecycle"
CONTRACT = "XAU_M5_POCKET_LIFECYCLE_LATENCY_V214"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
REACTION_WORKER = "ctrader_demo_xau_v201_reaction_ladder"


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


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _minutes(start: Any, end: Any) -> float | None:
    s = _dt(start)
    e = _dt(end)
    if s is None or e is None or e < s:
        return None
    return (e - s).total_seconds() / 60.0


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


def _range(pocket: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(pocket.get("low"))
    high = _f(pocket.get("high"))
    if low is None or high is None or high < low:
        return None
    return low, high


def _match_physical(
    pocket: dict[str, Any],
    direction: str,
    rows: Sequence[dict[str, Any]],
    *,
    tolerance: float = 0.06,
) -> dict[str, Any]:
    bounds = _range(pocket)
    if bounds is None:
        return {}
    low, high = bounds
    matches: list[tuple[float, dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        if str(row.get("direction") or "").upper() != direction:
            continue
        row_low = _f(row.get("pocket_low"))
        row_high = _f(row.get("pocket_high"))
        if row_low is None or row_high is None:
            continue
        distance = abs(row_low - low) + abs(row_high - high)
        if distance <= tolerance:
            matches.append((distance, row))
    if not matches:
        return {}
    matches.sort(
        key=lambda item: (
            item[0],
            _dt(item[1].get("first_seen_at")) or datetime.max.replace(tzinfo=UTC),
        )
    )
    return matches[0][1]


def _reaction_hits(physical: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for row in list(physical.get("reaction_ladder") or []):
        item = dict(row)
        multiple = _f(item.get("atr_multiple"))
        if multiple is None:
            continue
        key = f"{multiple:.2f}"
        output[key] = {
            "hit": bool(item.get("hit")),
            "first_hit_at": item.get("first_hit_at"),
            "minutes_from_touch": item.get("minutes_from_touch"),
            "chronology_state": item.get("chronology_state"),
        }
    return output


def _leg_lifecycle(
    leg: dict[str, Any],
    physical_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    direction = str(leg.get("direction") or "").upper()
    micro = dict(leg.get("micro_refinement") or {})
    reuse = dict(leg.get("zone_reuse_v200") or {})

    candidate = dict(
        micro.get("candidate_entry_pocket")
        or reuse.get("active_candidate_micro_pocket")
        or (
            leg.get("m5_pocket")
            if str(leg.get("pocket_state") or "").upper() == "CANDIDATE_M5_POCKET"
            else {}
        )
        or {}
    )
    refined = dict(
        micro.get("refined_entry_pocket")
        or reuse.get("active_refined_micro_pocket")
        or (
            leg.get("m5_pocket")
            if str(leg.get("pocket_state") or "").upper() == "REFINED_M5_POCKET"
            else {}
        )
        or {}
    )

    candidate_physical = _match_physical(candidate, direction, physical_rows)
    refined_physical = _match_physical(refined, direction, physical_rows)

    candidate_mapped_at = (
        candidate_physical.get("first_seen_at")
        or candidate.get("origin_at")
        or micro.get("sweep", {}).get("at")
    )
    first_touch_at = (
        candidate_physical.get("first_touch_at")
        or refined_physical.get("first_touch_at")
    )
    sweep_at = dict(micro.get("sweep") or {}).get("at")
    reclaim_at = micro.get("reclaim_at")
    mss_at = micro.get("mss_at")
    displacement_at = micro.get("displacement_at")
    refined_physical_first_seen = _dt(refined_physical.get("first_seen_at"))
    displacement_dt = _dt(displacement_at)
    refined_causal_ready = (
        None
        if displacement_dt is None
        else displacement_dt + timedelta(minutes=5)
    )
    if refined:
        if refined_physical_first_seen is not None and refined_causal_ready is not None:
            refined_mapped_dt = max(refined_physical_first_seen, refined_causal_ready)
        else:
            refined_mapped_dt = refined_physical_first_seen or refined_causal_ready
        refined_mapped_at = (
            None
            if refined_mapped_dt is None
            else refined_mapped_dt.isoformat()
        ) or refined.get("origin_at")
    else:
        refined_mapped_at = None

    reaction = _reaction_hits(candidate_physical or refined_physical)

    return {
        "direction": direction or None,
        "pocket_state": leg.get("pocket_state"),
        "initial_pocket": candidate,
        "refined_pocket": refined,
        "candidate_evidence": {
            "physical_key": candidate_physical.get("physical_key"),
            "first_seen_at": candidate_physical.get("first_seen_at"),
            "first_touch_at": candidate_physical.get("first_touch_at"),
            "premapped_before_touch": candidate_physical.get("premapped_before_touch"),
            "premap_lead_minutes": candidate_physical.get("premap_lead_minutes"),
            "status": candidate_physical.get("status"),
        },
        "refined_evidence": {
            "physical_key": refined_physical.get("physical_key"),
            "first_seen_at": refined_physical.get("first_seen_at"),
            "first_touch_at": refined_physical.get("first_touch_at"),
            "premapped_before_touch": refined_physical.get("premapped_before_touch"),
            "premap_lead_minutes": refined_physical.get("premap_lead_minutes"),
            "status": refined_physical.get("status"),
        },
        "timeline": {
            "candidate_mapped_at": candidate_mapped_at,
            "candidate_origin_at": candidate.get("origin_at"),
            "first_touch_at": first_touch_at,
            "sweep_at": sweep_at,
            "reclaim_at": reclaim_at,
            "mss_at": mss_at,
            "displacement_at": displacement_at,
            "refined_causal_ready_at": (
                None if refined_causal_ready is None else refined_causal_ready.isoformat()
            ),
            "refined_mapped_at": refined_mapped_at,
            "refined_origin_at": refined.get("origin_at"),
        },
        "latency_minutes": {
            "candidate_map_to_touch": _minutes(candidate_mapped_at, first_touch_at),
            "touch_to_reclaim": _minutes(first_touch_at, reclaim_at),
            "reclaim_to_mss": _minutes(reclaim_at, mss_at),
            "mss_to_displacement": _minutes(mss_at, displacement_at),
            "touch_to_refined": _minutes(first_touch_at, refined_mapped_at),
            "candidate_map_to_refined": _minutes(candidate_mapped_at, refined_mapped_at),
        },
        "reaction_ladder": reaction,
        "interpretation": (
            "Initial pocket is the pre-confirmation M5 candidate. Refined pocket is the "
            "post-reclaim/MSS/displacement retest pocket. A refined pocket can legitimately "
            "appear after the first reversal has begun, so it must not replace the initial "
            "pocket in latency analysis."
        ),
    }


def evaluate_lifecycle(
    projection: dict[str, Any],
    reaction_details: dict[str, Any],
) -> dict[str, Any]:
    physical_rows = [
        dict(row) for row in list(reaction_details.get("latest_physical_pockets") or [])
    ]
    current = _leg_lifecycle(dict(projection.get("current_leg") or {}), physical_rows)
    next_leg = _leg_lifecycle(dict(projection.get("next_leg") or {}), physical_rows)

    return {
        "contract": CONTRACT,
        "current_leg": current,
        "next_leg": next_leg,
        "physical_pockets_available": len(physical_rows),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "policy_effect": "SHADOW_ONLY",
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V214_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V214_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    error: str | None = None
    evaluation: dict[str, Any] = {}

    try:
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        reaction_hb = _latest_heartbeat(store, REACTION_WORKER)
        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        projection = dict(atlas_eval.get("m5_path_projection") or {})
        reaction_details = dict(reaction_hb.get("details") or {})
        evaluation = evaluate_lifecycle(projection, reaction_details)
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
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "policy_effect": "SHADOW_ONLY",
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V214_POCKET_LIFECYCLE "
        f"healthy={healthy} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

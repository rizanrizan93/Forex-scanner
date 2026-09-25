from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import os
from typing import Any

from .execution.policy import load_execution_policy
from .research_xau_supply_demand_reaction_v183 import PRE_REGISTERED_GROUPS
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v212_zone_reaction_probability"
CONTRACT = "XAU_ZONE_REACTION_PROBABILITY_V212"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
RESEARCH_WORKER = "ctrader_xau_supply_demand_reaction_v183"
PROSPECTIVE_WORKER = "ctrader_demo_xau_supply_demand_prospective_v184"

PRIOR_STRENGTH = 20.0
MIN_COHORT_N = 8


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _i(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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


def _touch_bucket(zone: dict[str, Any]) -> str:
    lifecycle = dict(zone.get("lifecycle") or {})
    count = _i(lifecycle.get("touch_count"))
    if count <= 1:
        return "FIRST_TEST"
    if count == 2:
        return "SECOND_TEST"
    return "MULTI_TESTED"


def _nesting_bucket(zone: dict[str, Any]) -> str:
    count = _i(zone.get("htf_nesting_count"))
    if count <= 0:
        return "NO_HTF_NESTING"
    if count == 1:
        return "ONE_HTF_PARENT"
    return "MULTI_HTF_NESTING"


def _liquidity_bucket(zone: dict[str, Any]) -> str:
    liquidity = dict(zone.get("liquidity") or {})
    count = _i(liquidity.get("confluence_count"))
    if count <= 0:
        return "NO_LIQUIDITY_CONFLUENCE"
    if count == 1:
        return "ONE_LIQUIDITY_CONFLUENCE"
    return "MULTI_LIQUIDITY_CONFLUENCE"


def _features(zone: dict[str, Any]) -> dict[str, str]:
    return {
        "timeframe": str(zone.get("timeframe") or "UNKNOWN"),
        "zone_class": str(zone.get("zone_class") or "UNKNOWN"),
        "pattern": str(zone.get("pattern") or "UNKNOWN"),
        "direction": str(zone.get("direction") or "UNKNOWN").upper(),
        "touch_bucket": _touch_bucket(zone),
        "age_bucket": str(zone.get("age_bucket") or "UNKNOWN"),
        "nesting_bucket": _nesting_bucket(zone),
        "approach_state": str(dict(zone.get("approach") or {}).get("state") or "UNKNOWN"),
        "session_context": str(zone.get("session_context") or "UNKNOWN"),
        "liquidity_bucket": _liquidity_bucket(zone),
    }


def _metric(row: dict[str, Any], key: str) -> float | None:
    value = _f(row.get(key))
    if value is not None:
        return value
    n = _i(row.get("n"))
    if n <= 0:
        return None
    if key == "p_break":
        return _i(row.get("breaks")) / n
    if key == "p_stall":
        return _i(row.get("stalls")) / n
    return None


def _shrink(value: float | None, *, n: int, prior: float | None) -> float | None:
    if value is None:
        return prior
    if prior is None:
        return value
    weight = max(0.0, float(n))
    return (weight * value + PRIOR_STRENGTH * prior) / (weight + PRIOR_STRENGTH)


def _matching_group(
    groups: dict[str, Any],
    fields: tuple[str, ...],
    features: dict[str, str],
) -> dict[str, Any] | None:
    rows = list(groups.get("|".join(fields)) or [])
    for row in rows:
        item = dict(row)
        dims = {str(k): str(v) for k, v in dict(item.get("dimensions") or {}).items()}
        if all(dims.get(field) == features.get(field) for field in fields):
            return item
    return None


def _touch_probability(zone: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    features = _features(zone)
    overall = dict(evaluation.get("destination_overall") or {})
    selected: dict[str, Any] | None = None
    for row in list(evaluation.get("destination_by_zone_type") or []):
        item = dict(row)
        dims = {str(k): str(v) for k, v in dict(item.get("dimensions") or {}).items()}
        if all(
            dims.get(field) == features.get(field)
            for field in ("timeframe", "zone_class", "pattern", "direction")
        ):
            selected = item
            break
    source = selected or overall
    return {
        "p_touch": _f(source.get("touch_rate")),
        "zones": _i(source.get("zones")),
        "resolved_zones": _i(source.get("resolved_zones")),
        "source": "ZONE_TYPE" if selected else "OVERALL",
    }


def _reaction_estimate(zone: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    features = _features(zone)
    groups = dict(evaluation.get("holdout_groups") or {})
    baseline = dict(evaluation.get("holdout_overall") or evaluation.get("development_overall") or {})

    baseline_metrics = {
        "p_hold_025": _metric(baseline, "hit_025"),
        "p_hold_050": _metric(baseline, "hit_050"),
        "p_hold_075": _metric(baseline, "hit_075"),
        "p_hold_100": _metric(baseline, "hit_100"),
        "p_break": _metric(baseline, "p_break"),
        "p_stall": _metric(baseline, "p_stall"),
        "median_mfe_atr": _metric(baseline, "median_mfe_atr"),
        "median_mae_atr": _metric(baseline, "median_mae_atr"),
        "p75_mae_atr": _metric(baseline, "p75_mae_atr"),
        "median_bars_to_outcome": _metric(baseline, "median_bars_to_outcome"),
    }

    cohort_rows: list[dict[str, Any]] = []
    estimates: list[dict[str, Any]] = []
    for fields in PRE_REGISTERED_GROUPS:
        row = _matching_group(groups, tuple(fields), features)
        if row is None:
            continue
        n = _i(row.get("n"))
        if n < MIN_COHORT_N:
            continue
        cohort_rows.append({
            "contract": list(fields),
            "dimensions": dict(row.get("dimensions") or {}),
            "n": n,
            "precision_hold": _f(row.get("precision_hold")),
            "wilson_lower_95": _f(row.get("wilson_lower_95")),
        })
        estimates.append({
            "n": n,
            **{
                key: _shrink(
                    _metric(row, source_key),
                    n=n,
                    prior=baseline_metrics.get(key),
                )
                for key, source_key in (
                    ("p_hold_025", "hit_025"),
                    ("p_hold_050", "hit_050"),
                    ("p_hold_075", "hit_075"),
                    ("p_hold_100", "hit_100"),
                    ("p_break", "p_break"),
                    ("p_stall", "p_stall"),
                    ("median_mfe_atr", "median_mfe_atr"),
                    ("median_mae_atr", "median_mae_atr"),
                    ("p75_mae_atr", "p75_mae_atr"),
                    ("median_bars_to_outcome", "median_bars_to_outcome"),
                )
            },
        })

    if estimates:
        weights = [max(0.01, min(1.0, item["n"] / 50.0)) for item in estimates]
        total_weight = sum(weights)
        combined: dict[str, Any] = {}
        for key in baseline_metrics:
            pairs = [
                (weight, item.get(key))
                for weight, item in zip(weights, estimates)
                if item.get(key) is not None
            ]
            combined[key] = (
                baseline_metrics.get(key)
                if not pairs
                else sum(weight * float(value) for weight, value in pairs)
                / sum(weight for weight, _ in pairs)
            )
    else:
        combined = dict(baseline_metrics)

    max_n = max((_i(item.get("n")) for item in cohort_rows), default=0)
    if len(cohort_rows) >= 3 and max_n >= 50:
        confidence = "HIGH_HISTORICAL_SUPPORT"
    elif cohort_rows and max_n >= 20:
        confidence = "MEDIUM_HISTORICAL_SUPPORT"
    else:
        confidence = "LOW_HISTORICAL_SUPPORT"

    p050 = _f(combined.get("p_hold_050"))
    p075 = _f(combined.get("p_hold_075"))
    p100 = _f(combined.get("p_hold_100"))
    combined["p_075_given_050"] = (
        None if p050 is None or p050 <= 0 or p075 is None else min(1.0, p075 / p050)
    )
    combined["p_100_given_050"] = (
        None if p050 is None or p050 <= 0 or p100 is None else min(1.0, p100 / p050)
    )

    return {
        **combined,
        "confidence": confidence,
        "matched_cohorts": cohort_rows,
        "matched_contracts": len(cohort_rows),
        "historical_holdout_n": _i(baseline.get("n")),
        "estimate_type": "SHRUNK_EMPIRICAL_HOLDOUT_ESTIMATE",
        "not_calibrated_probability_claim": True,
    }


def evaluate_zone_probabilities(
    zones: list[dict[str, Any]],
    research_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for zone in zones:
        item = dict(zone)
        output.append({
            "zone_id": item.get("zone_id"),
            "direction": item.get("direction"),
            "timeframe": item.get("timeframe"),
            "low": item.get("low"),
            "high": item.get("high"),
            "status": item.get("status"),
            "freshness": dict(item.get("lifecycle") or {}).get("freshness"),
            "research_score": item.get("research_score"),
            "features": _features(item),
            "destination": _touch_probability(item, research_evaluation),
            "reaction": _reaction_estimate(item, research_evaluation),
        })
    return output


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V212_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V212_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    results: list[dict[str, Any]] = []
    prospective_summary: dict[str, Any] = {}
    active_zone_probability: dict[str, Any] = {}
    next_zone_probability: dict[str, Any] = {}

    try:
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        research_hb = _latest_heartbeat(store, RESEARCH_WORKER)
        prospective_hb = _latest_heartbeat(store, PROSPECTIVE_WORKER)

        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        research_eval = dict(dict(research_hb.get("details") or {}).get("evaluation") or {})
        prospective_summary = dict(dict(prospective_hb.get("details") or {}).get("summary") or {})

        zones = [dict(row) for row in list(atlas_eval.get("zones") or [])]
        projection = dict(atlas_eval.get("m5_path_projection") or {})
        current_source = dict(dict(projection.get("current_leg") or {}).get("source_zone") or {})
        next_source = dict(dict(projection.get("next_leg") or {}).get("source_zone") or {})

        # The atlas display list is intentionally capped for the phone dashboard.
        # Always include the active/current and premapped next source even if either
        # one falls outside that display slice, so V213 never loses its probability
        # context because of a presentation limit.
        seen_zone_ids = {str(row.get("zone_id") or "") for row in zones}
        for source in (current_source, next_source):
            source_id = str(source.get("zone_id") or "")
            if source_id and source_id not in seen_zone_ids:
                zones.append(source)
                seen_zone_ids.add(source_id)

        results = evaluate_zone_probabilities(zones, research_eval)

        by_zone = {
            str(row.get("zone_id") or ""): row
            for row in results
            if row.get("zone_id")
        }
        active_zone_probability = by_zone.get(str(current_source.get("zone_id") or ""), {})
        next_zone_probability = by_zone.get(str(next_source.get("zone_id") or ""), {})
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
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "historical_source": RESEARCH_WORKER,
            "prospective_source": PROSPECTIVE_WORKER,
            "atlas_source": ATLAS_WORKER,
            "prior_strength": PRIOR_STRENGTH,
            "minimum_cohort_n": MIN_COHORT_N,
            "zone_probabilities": results,
            "active_zone_probability": active_zone_probability,
            "next_zone_probability": next_zone_probability,
            "prospective_overlay": prospective_summary,
            "interpretation": (
                "V212 ranks current zones with shrunk historical holdout estimates for touch, "
                "reaction, break and continuation. Values are shadow research estimates, not "
                "calibrated production probabilities and cannot alter trading authority."
            ),
            "observed_at": now.isoformat(),
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V212_ZONE_REACTION_PROBABILITY "
        f"healthy={healthy} zones={len(results)} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

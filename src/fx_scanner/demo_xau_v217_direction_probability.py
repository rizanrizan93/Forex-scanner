from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import os
from typing import Any

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v217_direction_probability"
CONTRACT = "XAU_DIRECTION_PROBABILITY_V217"
PATH_WORKER = "ctrader_demo_xau_v213_post_zone_path"
FORECAST_WORKER = "ctrader_xau_forecast_ensemble_v171"
SNAPSHOT_WORKER = "ctrader_demo_xau_v218_htf_strategic_snapshot"
REFERENCE_REGIME_WORKER = "ctrader_xau_htf_strategic_regime_v180"
REGIME_STALE_SECONDS = 6 * 60 * 60


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _clip01(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _latest_heartbeat(store: SupabaseOperationalStore, worker_name: str) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return max(0.0, (now - parsed.astimezone(UTC)).total_seconds())


def _select_regime_heartbeat(
    snapshot_heartbeat: dict[str, Any],
    reference_heartbeat: dict[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    snapshot_details = dict(snapshot_heartbeat.get("details") or {})
    snapshot_eval = dict(snapshot_details.get("evaluation") or {})
    snapshot_current = dict(snapshot_eval.get("current") or {})
    snapshot_parity = dict(snapshot_eval.get("parity") or {})
    snapshot_age = _age_seconds(snapshot_heartbeat.get("observed_at"), now=now)
    snapshot_usable = bool(
        snapshot_heartbeat.get("healthy")
        and snapshot_current
        and snapshot_age is not None
        and snapshot_age <= REGIME_STALE_SECONDS
        and snapshot_parity.get("trusted_for_context") is True
    )
    if snapshot_usable:
        return snapshot_heartbeat, SNAPSHOT_WORKER
    return reference_heartbeat, REFERENCE_REGIME_WORKER


def _empty_distribution(reason: str) -> dict[str, Any]:
    return {
        "p_long": None,
        "p_short": None,
        "p_neutral": None,
        "reason": reason,
    }


def empirical_leg_distribution(leg: dict[str, Any]) -> dict[str, Any]:
    direction = str(leg.get("direction") or "").upper()
    estimate = dict(leg.get("historical_estimate") or {})
    p_hold = _clip01(_f(estimate.get("p_hold_050")))
    p_break = _clip01(_f(estimate.get("p_break")))
    p_stall = _clip01(_f(estimate.get("p_stall")))

    if direction not in {"LONG", "SHORT"}:
        return {
            **_empty_distribution("LEG_DIRECTION_UNAVAILABLE"),
            "direction": direction or None,
            "stage": leg.get("stage"),
            "distribution_type": "UNAVAILABLE",
            "execution_influence": False,
        }
    if p_hold is None or p_break is None:
        return {
            **_empty_distribution("HOLD_OR_BREAK_ESTIMATE_UNAVAILABLE"),
            "direction": direction,
            "stage": leg.get("stage"),
            "distribution_type": "UNAVAILABLE",
            "execution_influence": False,
        }

    # V183 classifies the primary 0.50 ATR outcome as HOLD, BREAK, STALL or
    # right-censored PENDING. HOLD that occurs before a later break wins the
    # episode, so HOLD and BREAK are exclusive. V212 preserves those cohort
    # rates through shrinkage. The residual is therefore neutral/unresolved.
    directional_mass = p_hold + p_break
    if directional_mass > 1.0 + 1e-9:
        # Defensive normalization only for impossible numerical/model drift.
        p_hold = p_hold / directional_mass
        p_break = p_break / directional_mass
        p_neutral = 0.0
        normalization = "DEFENSIVE_RENORMALIZATION"
    else:
        p_neutral = max(0.0, 1.0 - directional_mass)
        normalization = "EXCLUSIVE_RESIDUAL"

    if direction == "LONG":
        p_long, p_short = p_hold, p_break
    else:
        p_long, p_short = p_break, p_hold

    unresolved = None
    if p_stall is not None:
        unresolved = max(0.0, p_neutral - p_stall)

    return {
        "p_long": p_long,
        "p_short": p_short,
        "p_neutral": p_neutral,
        "direction": direction,
        "stage": leg.get("stage"),
        "p_hold_050": p_hold,
        "p_break": p_break,
        "p_stall": p_stall,
        "p_unresolved_residual": unresolved,
        "normalization": normalization,
        "distribution_type": "SHRUNK_EMPIRICAL_HOLD_BREAK_RESIDUAL",
        "estimate_type": estimate.get("estimate_type"),
        "historical_confidence": estimate.get("confidence"),
        "matched_contracts": estimate.get("matched_contracts"),
        "median_minutes_to_outcome": estimate.get("median_minutes_to_outcome"),
        "not_fully_calibrated_probability_claim": True,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def strategic_support_distribution(
    forecast_details: dict[str, Any],
    regime_heartbeat: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    ensemble = dict(forecast_details.get("ensemble") or {})
    prior = dict(ensemble.get("directional_prior") or {})
    primary = dict(ensemble.get("primary_scenario") or {})
    path = dict(primary.get("structural_path") or {})
    score = _f(prior.get("score"))
    prior_direction = str(prior.get("direction") or "").upper()
    continuation = str(path.get("continuation") or "").upper()

    if score is None:
        distribution = _empty_distribution("V171_DIRECTIONAL_SCORE_UNAVAILABLE")
    else:
        clipped_score = max(-1.0, min(1.0, score))
        distribution = {
            "p_long": max(0.0, clipped_score),
            "p_short": max(0.0, -clipped_score),
            "p_neutral": 1.0 - abs(clipped_score),
            "reason": None,
        }

    regime_details = dict(regime_heartbeat.get("details") or {})
    regime_eval = dict(regime_details.get("evaluation") or {})
    regime_current = dict(regime_eval.get("current") or {})
    regime_parity = dict(regime_eval.get("parity") or {})
    regime_age = _age_seconds(regime_heartbeat.get("observed_at"), now=now)
    regime_fresh = bool(regime_age is not None and regime_age <= REGIME_STALE_SECONDS)
    regime_contract = str(regime_details.get("contract") or "")
    regime_source = (
        "V218_HTF_STRATEGIC_SNAPSHOT"
        if regime_contract == "XAU_HTF_STRATEGIC_SNAPSHOT_V218"
        else "V180_HTF_STRATEGIC_REGIME_REFERENCE"
    )

    return {
        **distribution,
        "distribution_type": "NORMALIZED_DIRECTIONAL_SUPPORT_NOT_CALIBRATED",
        "source": "V171_DIRECTIONAL_PRIOR_SCORE",
        "directional_prior": prior_direction or None,
        "direction_score": score,
        "primary_state": primary.get("direction"),
        "structural_continuation": continuation or None,
        "component_conflict": dict(ensemble.get("alternative_scenario") or {}).get(
            "component_conflict"
        ),
        "htf_context": {
            "source": regime_source,
            "contract": regime_contract or None,
            "fresh": regime_fresh,
            "age_seconds": regime_age,
            "strategic_bias": regime_current.get("strategic_bias"),
            "raw_direction": regime_current.get("raw_direction"),
            "raw_score": regime_current.get("raw_score"),
            "confidence": regime_current.get("confidence"),
            "map_at": regime_current.get("map_at"),
            "parity_state": regime_parity.get("state"),
            "parity_trusted": regime_parity.get("trusted_for_context"),
            "note": (
                "V218/V180 are context-only in V217. They are not converted into "
                "probability or blended into the V171 support distribution."
            ),
        },
        "not_fully_calibrated_probability_claim": True,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _dominant_direction(distribution: dict[str, Any]) -> str:
    values: list[tuple[str, float]] = []
    for direction, key in (
        ("LONG", "p_long"),
        ("SHORT", "p_short"),
        ("NEUTRAL", "p_neutral"),
    ):
        value = _f(distribution.get(key))
        if value is not None:
            values.append((direction, value))
    if not values:
        return "UNAVAILABLE"
    values.sort(key=lambda item: item[1], reverse=True)
    return values[0][0]


def evaluate_direction_probability(
    path_evaluation: dict[str, Any],
    forecast_details: dict[str, Any],
    regime_heartbeat: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    current_leg = dict(path_evaluation.get("current_leg") or {})
    next_leg = dict(path_evaluation.get("next_leg") or {})
    tactical = empirical_leg_distribution(current_leg)
    opposing = empirical_leg_distribution(next_leg)
    strategic = strategic_support_distribution(
        forecast_details,
        regime_heartbeat,
        now=now,
    )

    tactical_direction = str(current_leg.get("direction") or "").upper()
    strategic_direction = str(
        strategic.get("structural_continuation")
        or strategic.get("directional_prior")
        or ""
    ).upper()

    if tactical_direction in {"LONG", "SHORT"} and strategic_direction in {"LONG", "SHORT"}:
        relationship = (
            "ALIGNED"
            if tactical_direction == strategic_direction
            else "COUNTERTREND_FIRST_LEG"
        )
        sequential_path = (
            tactical_direction
            if relationship == "ALIGNED"
            else f"{tactical_direction}_THEN_{strategic_direction}"
        )
    else:
        relationship = "INSUFFICIENT_DIRECTION_CONTEXT"
        sequential_path = None

    return {
        "contract": CONTRACT,
        "state": (
            "DIRECTION_PROBABILITY_AVAILABLE"
            if tactical.get("p_long") is not None
            else "TACTICAL_PROBABILITY_UNAVAILABLE"
        ),
        "strategic_htf": strategic,
        "tactical_first_leg": tactical,
        "opposing_next_leg": opposing,
        "relationship": {
            "state": relationship,
            "sequential_path": sequential_path,
            "interpretation": (
                "Strategic HTF continuation and tactical first leg are separate horizons. "
                "A countertrend first leg is valid context, not a voting conflict."
            ),
        },
        "prospective_context": dict(
            path_evaluation.get("prospective_v197_v198_overlay") or {}
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "Tactical and opposing-leg probabilities are derived from V212/V213 shrunk "
            "historical HOLD/BREAK outcomes at the 0.50 ATR primary reaction threshold. "
            "Strategic values are normalized V171 directional support only and must not "
            "be described as calibrated production probabilities. V217 cannot create, "
            "block or size an order."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V217_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V217_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    evaluation: dict[str, Any] = {}
    error: str | None = None

    try:
        path_hb = _latest_heartbeat(store, PATH_WORKER)
        forecast_hb = _latest_heartbeat(store, FORECAST_WORKER)
        snapshot_hb = _latest_heartbeat(store, SNAPSHOT_WORKER)
        reference_regime_hb = _latest_heartbeat(store, REFERENCE_REGIME_WORKER)
        regime_hb, regime_source_worker = _select_regime_heartbeat(
            snapshot_hb,
            reference_regime_hb,
            now=now,
        )

        path_eval = dict(dict(path_hb.get("details") or {}).get("evaluation") or {})
        forecast_details = dict(forecast_hb.get("details") or {})
        evaluation = evaluate_direction_probability(
            path_eval,
            forecast_details,
            regime_hb,
            now=now,
        )
        evaluation["source_freshness"] = {
            "v213_observed_at": path_hb.get("observed_at"),
            "v171_observed_at": forecast_hb.get("observed_at"),
            "v218_observed_at": snapshot_hb.get("observed_at"),
            "v180_observed_at": reference_regime_hb.get("observed_at"),
            "htf_context_worker": regime_source_worker,
        }
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
            "error": error,
            "observed_at": now.isoformat(),
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V217_DIRECTION_PROBABILITY "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

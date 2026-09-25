from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import os
from typing import Any, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_xau_htf_strategic_regime_v180 import (
    RESEARCH_VERSION as V180_RESEARCH_VERSION,
    STRONG_SWITCH_THRESHOLD,
    RegimePoint,
    build_regime_points,
)
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v218_htf_strategic_snapshot"
CONTRACT = "XAU_HTF_STRATEGIC_SNAPSHOT_V218"
REFERENCE_WORKER = "ctrader_xau_htf_strategic_regime_v180"

DEFAULT_HISTORY_BARS = 20_000
MIN_HISTORY_BARS = 8_000
MAX_HISTORY_BARS = 40_000
PARITY_MAX_RAW_SCORE_DELTA = 0.02
PARITY_MAX_COMPONENT_DELTA = 0.05


def _history_target() -> int:
    raw = os.getenv("XAU_V218_HISTORY_BARS", str(DEFAULT_HISTORY_BARS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("XAU_V218_HISTORY_BARS_INVALID") from exc
    if not MIN_HISTORY_BARS <= value <= MAX_HISTORY_BARS:
        raise SystemExit("XAU_V218_HISTORY_BARS_OUT_OF_RANGE")
    return value


def _latest_heartbeat(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any]:
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


def _snapshot(point: RegimePoint) -> dict[str, Any]:
    return {
        "map_at": ensure_utc(point.map_at).isoformat(),
        "price": float(point.close),
        "strategic_bias": point.strategic_bias,
        "raw_direction": point.raw_direction,
        "raw_score": float(point.raw_score),
        "confidence": min(
            1.0,
            abs(float(point.raw_score)) / float(STRONG_SWITCH_THRESHOLD),
        ),
        "baseline_h4_direction": point.baseline_h4_direction,
        "tactical_first_leg": (
            "LONG"
            if point.strategic_bias == "SHORT"
            else "SHORT"
            if point.strategic_bias == "LONG"
            else "NEUTRAL"
        ),
        "switch_pending_direction": point.switch_pending_direction,
        "switch_pending_count": int(point.switch_pending_count),
        "neutral_pending_count": int(point.neutral_pending_count),
        "components": dict(point.components),
    }


def _reference_current(reference_heartbeat: dict[str, Any]) -> dict[str, Any]:
    details = dict(reference_heartbeat.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    return dict(evaluation.get("current") or {})


def _point_at(
    points: Sequence[RegimePoint],
    map_at: Any,
) -> RegimePoint | None:
    if map_at in (None, ""):
        return None
    try:
        target = ensure_utc(datetime.fromisoformat(str(map_at).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None
    for point in reversed(tuple(points)):
        if ensure_utc(point.map_at) == target:
            return point
    return None


def parity_against_v180(
    points: Sequence[RegimePoint],
    reference_heartbeat: dict[str, Any],
) -> dict[str, Any]:
    current = _reference_current(reference_heartbeat)
    reference_map = current.get("map_at")
    if not current or reference_map in (None, ""):
        return {
            "state": "NO_REFERENCE",
            "trusted_for_context": False,
            "reference_map_at": reference_map,
            "reason": "V180_REFERENCE_CURRENT_UNAVAILABLE",
        }

    point = _point_at(points, reference_map)
    if point is None:
        return {
            "state": "REFERENCE_OUTSIDE_WINDOW",
            "trusted_for_context": False,
            "reference_map_at": reference_map,
            "reason": "V180_REFERENCE_MAP_NOT_IN_V218_WINDOW",
        }

    bounded = _snapshot(point)
    ref_score = current.get("raw_score")
    try:
        ref_score_f = float(ref_score)
    except (TypeError, ValueError):
        ref_score_f = float("nan")
    score_delta = (
        None
        if not isfinite(ref_score_f)
        else abs(float(bounded["raw_score"]) - ref_score_f)
    )

    reference_components = dict(current.get("components") or {})
    bounded_components = dict(bounded.get("components") or {})
    component_deltas: dict[str, float] = {}
    for name, bounded_value in bounded_components.items():
        try:
            reference_value = float(reference_components[name])
            bounded_value_f = float(bounded_value)
        except (KeyError, TypeError, ValueError):
            continue
        if isfinite(reference_value) and isfinite(bounded_value_f):
            component_deltas[name] = abs(bounded_value_f - reference_value)

    max_component_delta = (
        None if not component_deltas else max(component_deltas.values())
    )
    same_raw = str(bounded.get("raw_direction")) == str(current.get("raw_direction"))
    same_bias = str(bounded.get("strategic_bias")) == str(current.get("strategic_bias"))
    score_ok = score_delta is not None and score_delta <= PARITY_MAX_RAW_SCORE_DELTA
    components_ok = (
        max_component_delta is None
        or max_component_delta <= PARITY_MAX_COMPONENT_DELTA
    )
    passed = bool(same_raw and same_bias and score_ok and components_ok)

    return {
        "state": "PASS" if passed else "DRIFT",
        "trusted_for_context": passed,
        "reference_map_at": reference_map,
        "reference_observed_at": reference_heartbeat.get("observed_at"),
        "same_raw_direction": same_raw,
        "same_strategic_bias": same_bias,
        "raw_score_delta": score_delta,
        "max_component_delta": max_component_delta,
        "raw_score_tolerance": PARITY_MAX_RAW_SCORE_DELTA,
        "component_tolerance": PARITY_MAX_COMPONENT_DELTA,
        "bounded_reference_snapshot": bounded,
        "reference_snapshot": current,
    }


def build_snapshot_evaluation(
    bars: Sequence[Bar],
    reference_heartbeat: dict[str, Any],
) -> dict[str, Any]:
    points = build_regime_points(bars)
    if not points:
        return {
            "contract": CONTRACT,
            "state": "DATA_INSUFFICIENT",
            "source_algorithm": V180_RESEARCH_VERSION,
            "current": {},
            "parity": {
                "state": "NOT_EVALUATED",
                "trusted_for_context": False,
            },
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    current = _snapshot(points[-1])
    parity = parity_against_v180(points, reference_heartbeat)
    return {
        "contract": CONTRACT,
        "state": "HTF_SNAPSHOT_AVAILABLE",
        "source_algorithm": V180_RESEARCH_VERSION,
        "method": {
            "inputs": "COMPLETED_D1_AND_H4_ONLY",
            "bounded_history": True,
            "history_role": (
                "Current-state refresh only. V180 100K remains the research/parity anchor."
            ),
        },
        "current": current,
        "parity": parity,
        "context_ready": bool(parity.get("trusted_for_context")),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V218_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V218_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_V218_SYMBOL_NOT_CONFIGURED")

    store = SupabaseOperationalStore.from_env()
    observed_at = datetime.now(tz=UTC)
    target = _history_target()
    error: str | None = None
    evaluation: dict[str, Any] = {}
    pages: list[dict[str, Any]] = []
    actual = 0

    try:
        feed = build_ctrader_research_feed(policy, (SYMBOL,))
        try:
            feed.ensure_connected()
            bars, pages = _fetch_history(feed, target=target, as_of=observed_at)
        finally:
            try:
                feed.close()
            except Exception:
                pass

        actual = len(bars)
        reference = _latest_heartbeat(store, REFERENCE_WORKER)
        evaluation = build_snapshot_evaluation(bars, reference)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = bool(
        error is None
        and evaluation.get("state") == "HTF_SNAPSHOT_AVAILABLE"
    )
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "evaluation": evaluation,
            "history_target_bars": target,
            "history_actual_closed_bars": actual,
            "history_pages": pages,
            "reference_worker": REFERENCE_WORKER,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "observed_at": observed_at.isoformat(),
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V218_HTF_STRATEGIC_SNAPSHOT "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} "
        f"parity={dict(evaluation.get('parity') or {}).get('state','NONE')} "
        f"bars={actual}/{target} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

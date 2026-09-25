from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
import os
from typing import Any, Sequence

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v222_m5_pocket_quality"
CONTRACT = "XAU_M5_POCKET_QUALITY_V222"
V214_WORKER = "ctrader_demo_xau_v214_pocket_lifecycle"
V216_WORKER = "ctrader_demo_xau_v216_lifecycle_calibration"
V217_WORKER = "ctrader_demo_xau_v217_direction_probability"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
SHOCK_WORKER = "ctrader_demo_xau_v203_volatility_shock_guard"
EVENT_TYPE = "DEMO_XAU_M5_LIFECYCLE_V215"
ACCOUNT_ID = "OBSERVABILITY"
LOOKBACK_HOURS = 6
MAX_ROWS = 1200
MAX_FAMILY_ROWS = 12
M5_MINUTES = 5


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


def _recent_events(
    store: SupabaseOperationalStore,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", ACCOUNT_ID)
        .eq("event_type", EVENT_TYPE)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=False)
        .limit(MAX_ROWS)
        .execute()
    )
    return [dict(row) for row in list(response.data or [])]


def _collapse_events(
    rows: Sequence[dict[str, Any]],
    *,
    role: str,
    direction: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        payload = dict(row.get("payload") or {})
        if str(payload.get("role") or "") != role:
            continue
        if str(payload.get("direction") or "").upper() != direction:
            continue
        key = str(row.get("signal_key") or payload.get("signal_key") or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(row)

    output: list[dict[str, Any]] = []
    for key, group in grouped.items():
        group.sort(key=lambda item: _dt(item.get("observed_at")) or datetime.max.replace(tzinfo=UTC))
        first = dict(group[0].get("payload") or {})
        latest = dict(group[-1].get("payload") or {})
        refined_rows = [
            row
            for row in group
            if dict(dict(row).get("payload") or {}).get("refined_pocket")
        ]
        refined_first_observed_at = (
            None if not refined_rows else refined_rows[0].get("observed_at")
        )
        output.append(
            {
                "signal_key": key,
                "first_observed_at": group[0].get("observed_at"),
                "latest_observed_at": group[-1].get("observed_at"),
                "refined_first_observed_at": refined_first_observed_at,
                "first": first,
                "latest": latest,
            }
        )
    output.sort(
        key=lambda item: _dt(item.get("first_observed_at"))
        or datetime.max.replace(tzinfo=UTC)
    )
    return output[-MAX_FAMILY_ROWS:]


def _processing_delay_after_close(
    origin_at: Any,
    mapped_at: Any,
) -> float | None:
    origin = _dt(origin_at)
    mapped = _dt(mapped_at)
    if origin is None or mapped is None:
        return None
    eligible = origin + timedelta(minutes=M5_MINUTES)
    return max(0.0, (mapped - eligible).total_seconds() / 60.0)


def _distance_from_pocket(
    *,
    direction: str,
    low: float,
    high: float,
    price: float | None,
) -> dict[str, Any]:
    if price is None:
        return {
            "points": None,
            "favorable_away_points": None,
            "inside": None,
            "side": "UNKNOWN",
        }
    inside = low <= price <= high
    if inside:
        return {
            "points": 0.0,
            "favorable_away_points": 0.0,
            "inside": True,
            "side": "INSIDE",
        }
    if price < low:
        distance = low - price
        favorable = distance if direction == "SHORT" else 0.0
        return {
            "points": distance,
            "favorable_away_points": favorable,
            "inside": False,
            "side": "BELOW",
        }
    distance = price - high
    favorable = distance if direction == "LONG" else 0.0
    return {
        "points": distance,
        "favorable_away_points": favorable,
        "inside": False,
        "side": "ABOVE",
    }


def _timing_state(
    *,
    first_touch_at: Any,
    distance_atr: float | None,
    inside: bool | None,
) -> str:
    if _dt(first_touch_at) is not None:
        return "POST_MAP_TOUCH_CONFIRMED"
    if inside is True:
        return "AT_POCKET_WAIT_CONFIRMATION"
    if distance_atr is not None and distance_atr >= 0.25:
        return "LATE_FOR_FIRST_ENTRY_WAIT_RETEST"
    if distance_atr is not None and distance_atr >= 0.10:
        return "MOVE_STARTED_WAIT_RETEST"
    return "FRESH_ORIGIN_WAIT_RETEST"


def _quality_score(
    *,
    processing_delay_minutes: float | None,
    width_atr: float | None,
    parent_research_score: float | None,
    parent_freshness: str,
    tactical_hold_probability: float | None,
    revision_index: int,
    timing_state: str,
    shock_state: str,
) -> float:
    score = 50.0

    if processing_delay_minutes is not None:
        if processing_delay_minutes <= 1.0:
            score += 8.0
        elif processing_delay_minutes <= 3.0:
            score += 4.0
        elif processing_delay_minutes > 5.0:
            score -= 5.0

    if width_atr is not None:
        if 0.04 <= width_atr <= 0.30:
            score += 5.0
        elif width_atr > 0.50:
            score -= 5.0

    if parent_research_score is not None:
        score += _clamp((parent_research_score - 50.0) * 0.20, -8.0, 8.0)

    freshness = str(parent_freshness or "").upper()
    score += {
        "FRESH": 5.0,
        "PARTIALLY_MITIGATED": -2.0,
        "MULTI_TESTED": -4.0,
        "DEEPLY_MITIGATED": -6.0,
    }.get(freshness, 0.0)

    if tactical_hold_probability is not None:
        score += _clamp((tactical_hold_probability - 0.50) * 20.0, -6.0, 6.0)

    score -= min(8.0, max(0, revision_index - 1) * 2.0)

    score += {
        "POST_MAP_TOUCH_CONFIRMED": 8.0,
        "AT_POCKET_WAIT_CONFIRMATION": 3.0,
        "MOVE_STARTED_WAIT_RETEST": -5.0,
        "LATE_FOR_FIRST_ENTRY_WAIT_RETEST": -12.0,
    }.get(timing_state, 0.0)

    shock = str(shock_state or "").upper()
    if shock == "SHOCK":
        score -= 8.0
    elif shock in {"ELEVATED", "STABILIZING"}:
        score -= 3.0
    elif shock == "NORMAL":
        score += 2.0

    return round(_clamp(score, 0.0, 100.0), 2)


def _family_state(midpoints: Sequence[float]) -> str:
    if len(midpoints) < 3:
        return "INSUFFICIENT_REVISIONS"
    deltas = [b - a for a, b in zip(midpoints, midpoints[1:])]
    positive = all(delta > 0 for delta in deltas)
    negative = all(delta < 0 for delta in deltas)
    if positive:
        return "SEQUENTIAL_REMAP_UP"
    if negative:
        return "SEQUENTIAL_REMAP_DOWN"
    return "MIXED_REMAP"


def build_quality_evaluation(
    *,
    events: Sequence[dict[str, Any]],
    lifecycle: dict[str, Any],
    atlas_evaluation: dict[str, Any],
    calibration_summary: dict[str, Any],
    direction_evaluation: dict[str, Any],
    shock_details: dict[str, Any],
) -> dict[str, Any]:
    current_leg = dict(lifecycle.get("current_leg") or {})
    direction = str(current_leg.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return {
            "contract": CONTRACT,
            "state": "NO_CURRENT_DIRECTION",
            "family": [],
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    family = _collapse_events(events, role="current_leg", direction=direction)
    path_projection = dict(atlas_evaluation.get("m5_path_projection") or {})
    projected_leg = dict(path_projection.get("current_leg") or {})
    parent = dict(projected_leg.get("source_zone") or {})
    parent_atr = _f(parent.get("atr_points"))
    parent_score = _f(parent.get("research_score"))
    parent_freshness = str(dict(parent.get("lifecycle") or {}).get("freshness") or "")
    price_now = _f(atlas_evaluation.get("last_closed_m15_price"))

    tactical = dict(direction_evaluation.get("tactical_first_leg") or {})
    tactical_hold = _f(tactical.get("p_hold_050"))
    shock_state = str(
        dict(shock_details.get("evaluation") or {}).get("state")
        or shock_details.get("state")
        or "UNKNOWN"
    ).upper()

    rows: list[dict[str, Any]] = []
    midpoints: list[float] = []
    previous_mid: float | None = None

    for index, episode in enumerate(family, start=1):
        first = dict(episode.get("first") or {})
        latest = dict(episode.get("latest") or {})
        pocket = dict(first.get("initial_pocket") or latest.get("initial_pocket") or {})
        timeline_first = dict(first.get("timeline") or {})
        timeline_latest = dict(latest.get("timeline") or {})
        low = _f(pocket.get("low"))
        high = _f(pocket.get("high"))
        if low is None or high is None or high < low:
            continue

        mid = (low + high) / 2.0
        midpoints.append(mid)
        mapped_at = (
            timeline_first.get("candidate_mapped_at")
            or episode.get("first_observed_at")
        )
        origin_at = pocket.get("origin_at")
        first_touch_at = timeline_latest.get("first_touch_at")
        delay = _processing_delay_after_close(origin_at, mapped_at)
        width_atr = None if not parent_atr else (high - low) / parent_atr
        distance = _distance_from_pocket(
            direction=direction,
            low=low,
            high=high,
            price=price_now,
        )
        favorable_away_atr = (
            None
            if parent_atr in (None, 0) or distance["favorable_away_points"] is None
            else float(distance["favorable_away_points"]) / float(parent_atr)
        )
        timing_state = _timing_state(
            first_touch_at=first_touch_at,
            distance_atr=favorable_away_atr,
            inside=distance["inside"],
        )
        midpoint_shift = None if previous_mid is None else mid - previous_mid
        midpoint_shift_atr = (
            None
            if midpoint_shift is None or parent_atr in (None, 0)
            else midpoint_shift / float(parent_atr)
        )
        score = _quality_score(
            processing_delay_minutes=delay,
            width_atr=width_atr,
            parent_research_score=parent_score,
            parent_freshness=parent_freshness,
            tactical_hold_probability=tactical_hold,
            revision_index=index,
            timing_state=timing_state,
            shock_state=shock_state,
        )
        refined_first_observed_at = episode.get("refined_first_observed_at")
        candidate_dt = _dt(mapped_at)
        refined_observed_dt = _dt(refined_first_observed_at)
        candidate_to_refined_observed_minutes = (
            None
            if candidate_dt is None or refined_observed_dt is None
            else max(
                0.0,
                (refined_observed_dt - candidate_dt).total_seconds() / 60.0,
            )
        )
        refinement_timing_state = (
            "NOT_REFINED"
            if refined_observed_dt is None
            else "REFINED_LATE_RETEST_ONLY"
            if (
                candidate_to_refined_observed_minutes is not None
                and candidate_to_refined_observed_minutes >= 10.0
            )
            else "REFINED_TIMELY_CONFIRMATION"
        )

        rows.append(
            {
                "sequence": index,
                "signal_key": episode.get("signal_key"),
                "direction": direction,
                "low": low,
                "high": high,
                "mid": mid,
                "origin_at": origin_at,
                "mapped_at": mapped_at,
                "stage_latest": latest.get("stage"),
                "first_touch_at": first_touch_at,
                "refined": bool(dict(latest.get("refined_pocket") or {})),
                "refined_first_observed_at": refined_first_observed_at,
                "candidate_to_refined_observed_minutes": candidate_to_refined_observed_minutes,
                "refinement_timing_state": refinement_timing_state,
                "processing_delay_after_close_minutes": delay,
                "formation_price_was_already_traded": True,
                "touch_semantics": (
                    "first_touch_at means a post-map retest. The origin/formation candle "
                    "does not count as a tradable retest."
                ),
                "width_atr": width_atr,
                "current_price_reference": price_now,
                "distance_points": distance["points"],
                "favorable_away_atr": favorable_away_atr,
                "timing_state": timing_state,
                "midpoint_shift_from_previous": midpoint_shift,
                "midpoint_shift_atr": midpoint_shift_atr,
                "quality_score_research": score,
                "display_role": (
                    "RETEST_REFERENCE"
                    if timing_state == "LATE_FOR_FIRST_ENTRY_WAIT_RETEST"
                    else "ACTIVE_RESEARCH_POCKET"
                ),
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
            }
        )
        previous_mid = mid

    latest_row = rows[-1] if rows else {}
    eligible_for_first_entry = [
        row
        for row in rows
        if str(row.get("timing_state")) not in {
            "LATE_FOR_FIRST_ENTRY_WAIT_RETEST",
        }
    ]
    best_research = (
        max(eligible_for_first_entry, key=lambda row: float(row.get("quality_score_research") or 0.0))
        if eligible_for_first_entry
        else {}
    )

    reaction_025 = dict(calibration_summary.get("candidate_hit_025_given_touch") or {})
    reaction_050 = dict(calibration_summary.get("candidate_hit_050_given_touch") or {})
    reaction_100 = dict(calibration_summary.get("candidate_hit_100_given_touch") or {})

    return {
        "contract": CONTRACT,
        "state": "POCKET_FAMILY_AVAILABLE" if rows else "NO_RECENT_POCKET_FAMILY",
        "direction": direction,
        "current_price_reference": price_now,
        "parent_context": {
            "zone_id": parent.get("zone_id"),
            "timeframe": parent.get("timeframe"),
            "low": parent.get("low"),
            "high": parent.get("high"),
            "atr_points": parent_atr,
            "research_score": parent_score,
            "freshness": parent_freshness,
        },
        "family_state": _family_state(midpoints),
        "family_count": len(rows),
        "latest_pocket": latest_row,
        "best_research_pocket": best_research,
        "family": rows,
        "observed_reaction_baseline": {
            "sample_state": calibration_summary.get("sample_state"),
            "touched": calibration_summary.get("touched"),
            "p_hit_025_given_touch": reaction_025,
            "p_hit_050_given_touch": reaction_050,
            "p_hit_100_given_touch": reaction_100,
            "note": (
                "These are prospective V216 observed rates, not calibrated pocket-specific probabilities."
            ),
        },
        "interpretation": (
            "V222 separates formation/origin from a post-map retest and measures "
            "the first actual observation of the refined label. A pocket can be computed "
            "promptly after a completed M5 candle yet still be too late for a first entry "
            "because price already displaced away during formation. Sequential new sweep "
            "origins are retained as a pocket family instead of letting the newest geometry "
            "silently replace earlier candidates."
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V222_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V222_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    evaluation: dict[str, Any] = {}

    try:
        events = _recent_events(store, now=now)
        v214 = _latest_heartbeat(store, V214_WORKER)
        v216 = _latest_heartbeat(store, V216_WORKER)
        v217 = _latest_heartbeat(store, V217_WORKER)
        atlas = _latest_heartbeat(store, ATLAS_WORKER)
        shock = _latest_heartbeat(store, SHOCK_WORKER)

        lifecycle = dict(dict(v214.get("details") or {}).get("evaluation") or {})
        calibration_summary = dict(dict(v216.get("details") or {}).get("summary") or {})
        direction_evaluation = dict(dict(v217.get("details") or {}).get("evaluation") or {})
        atlas_evaluation = dict(dict(atlas.get("details") or {}).get("evaluation") or {})
        shock_details = dict(shock.get("details") or {})

        evaluation = build_quality_evaluation(
            events=events,
            lifecycle=lifecycle,
            atlas_evaluation=atlas_evaluation,
            calibration_summary=calibration_summary,
            direction_evaluation=direction_evaluation,
            shock_details=shock_details,
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
            "lookback_hours": LOOKBACK_HOURS,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": now.isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V222_M5_POCKET_QUALITY "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} "
        f"family_count={evaluation.get('family_count',0)} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sqrt
import os
from statistics import median
from typing import Any

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v216_lifecycle_calibration"
CONTRACT = "XAU_M5_LIFECYCLE_CALIBRATION_V216"
EVENT_TYPE = "DEMO_XAU_M5_LIFECYCLE_V215"
ACCOUNT_ID = "OBSERVABILITY"
LOOKBACK_DAYS = 30
MAX_ROWS = 3000


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
        return float(value)
    except (TypeError, ValueError):
        return None


def _wilson_lower(hits: int, total: int, z: float = 1.96) -> float | None:
    if total <= 0:
        return None
    p = hits / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    margin = z * sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _events(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    cutoff = datetime.now(tz=UTC) - timedelta(days=LOOKBACK_DAYS)
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


def _episode_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(
        rows,
        key=lambda row: _dt(row.get("observed_at")) or datetime.max.replace(tzinfo=UTC),
    )
    payloads = [dict(row.get("payload") or {}) for row in rows]
    latest = payloads[-1] if payloads else {}
    candidate_time: datetime | None = None
    touch_time: datetime | None = None
    reclaim_time: datetime | None = None
    mss_time: datetime | None = None
    displacement_time: datetime | None = None
    refined_time: datetime | None = None
    reaction_times: dict[str, datetime] = {}
    premap_lead: float | None = None

    for payload in payloads:
        timeline = dict(payload.get("timeline") or {})
        candidate_time = candidate_time or _dt(timeline.get("candidate_mapped_at"))
        touch_time = touch_time or _dt(timeline.get("first_touch_at"))
        reclaim_time = reclaim_time or _dt(timeline.get("reclaim_at"))
        mss_time = mss_time or _dt(timeline.get("mss_at"))
        displacement_time = displacement_time or _dt(timeline.get("displacement_at"))
        refined_time = refined_time or _dt(timeline.get("refined_mapped_at"))

        evidence = dict(payload.get("candidate_evidence") or {})
        if premap_lead is None:
            premap_lead = _f(evidence.get("premap_lead_minutes"))

        ladder = dict(payload.get("reaction_ladder") or {})
        for rung, raw in ladder.items():
            item = dict(raw or {})
            if not bool(item.get("hit")):
                continue
            hit_at = _dt(item.get("first_hit_at"))
            if hit_at is not None and rung not in reaction_times:
                reaction_times[str(rung)] = hit_at

    def before(left: datetime | None, right: datetime | None) -> bool | None:
        if left is None or right is None:
            return None
        return left <= right

    return {
        "signal_key": str(rows[0].get("signal_key") or "") if rows else "",
        "direction": latest.get("direction"),
        "role": latest.get("role"),
        "candidate_mapped_at": None if candidate_time is None else candidate_time.isoformat(),
        "first_touch_at": None if touch_time is None else touch_time.isoformat(),
        "reclaim_at": None if reclaim_time is None else reclaim_time.isoformat(),
        "mss_at": None if mss_time is None else mss_time.isoformat(),
        "displacement_at": None if displacement_time is None else displacement_time.isoformat(),
        "refined_mapped_at": None if refined_time is None else refined_time.isoformat(),
        "premap_lead_minutes": premap_lead,
        "touched": touch_time is not None,
        "refined": refined_time is not None,
        "hit_025": "0.25" in reaction_times,
        "hit_050": "0.50" in reaction_times,
        "hit_075": "0.75" in reaction_times,
        "hit_100": "1.00" in reaction_times,
        "reaction_025_before_refined": before(reaction_times.get("0.25"), refined_time),
        "reaction_050_before_refined": before(reaction_times.get("0.50"), refined_time),
        "reaction_075_before_refined": before(reaction_times.get("0.75"), refined_time),
        "reaction_100_before_refined": before(reaction_times.get("1.00"), refined_time),
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        key = str(row.get("signal_key") or "")
        if key:
            grouped.setdefault(key, []).append(row)

    episodes = [_episode_summary(rows) for rows in grouped.values()]
    touched = [row for row in episodes if row["touched"]]
    refined = [row for row in episodes if row["refined"]]
    touched_refined = [row for row in touched if row["refined"]]

    leads = [
        float(row["premap_lead_minutes"])
        for row in touched
        if row.get("premap_lead_minutes") is not None
    ]

    def rate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        decisive = [row for row in rows if row.get(key) is not None]
        hits = sum(1 for row in decisive if bool(row.get(key)))
        return {
            "hits": hits,
            "n": len(decisive),
            "rate": None if not decisive else hits / len(decisive),
            "wilson_lower_95": _wilson_lower(hits, len(decisive)),
        }

    return {
        "contract": CONTRACT,
        "events": len(events),
        "episodes": len(episodes),
        "touched": len(touched),
        "refined": len(refined),
        "touched_and_refined": len(touched_refined),
        "refinement_rate_given_touch": (
            None if not touched else len(touched_refined) / len(touched)
        ),
        "candidate_hit_025_given_touch": rate(touched, "hit_025"),
        "candidate_hit_050_given_touch": rate(touched, "hit_050"),
        "candidate_hit_075_given_touch": rate(touched, "hit_075"),
        "candidate_hit_100_given_touch": rate(touched, "hit_100"),
        "reaction_025_before_refined": rate(touched_refined, "reaction_025_before_refined"),
        "reaction_050_before_refined": rate(touched_refined, "reaction_050_before_refined"),
        "reaction_075_before_refined": rate(touched_refined, "reaction_075_before_refined"),
        "reaction_100_before_refined": rate(touched_refined, "reaction_100_before_refined"),
        "median_premap_lead_minutes": None if not leads else median(leads),
        "episodes_latest": episodes[-20:],
        "sample_state": (
            "COLLECTING"
            if len(touched) < 30
            else "EARLY"
            if len(touched) < 100
            else "MATURE"
        ),
        "promotion_authority": False,
        "execution_influence": False,
        "execution_authority": False,
        "interpretation": (
            "V216 measures whether initial candidate pockets provide useful reaction evidence "
            "before the refined pocket is available. A high reaction-before-refined rate means "
            "refinement is better interpreted as retest/re-entry confirmation rather than the "
            "earliest reversal locator. Prospective sample size and Wilson lower bounds govern "
            "confidence; this layer cannot change execution."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V216_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V216_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    error: str | None = None
    summary: dict[str, Any] = {}

    try:
        summary = summarize(_events(store))
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "summary": summary,
            "lookback_days": LOOKBACK_DAYS,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": datetime.now(tz=UTC).isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V216_LIFECYCLE_CALIBRATION "
        f"healthy={healthy} episodes={summary.get('episodes',0)} "
        f"touched={summary.get('touched',0)} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

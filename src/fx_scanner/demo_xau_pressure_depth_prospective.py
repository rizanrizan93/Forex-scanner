from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
import os
from statistics import median
from typing import Any, Sequence

from .demo_xau_v227_depth_map_prospective import OUTCOME_EVENT
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_pressure_depth_prospective"
CONTRACT = "XAU_DOM_PRESSURE_TO_DEPTH_PROSPECTIVE_V247"
LOOKBACK_DAYS = 120
MAX_OUTCOMES = 2500
DOM_MATCH_BEFORE_SECONDS = 90
DOM_MATCH_AFTER_SECONDS = 60

BUCKETS = (
    (-100.0, -40.0, "COUNTER_STRONG"),
    (-40.0, -15.0, "COUNTER_MODERATE"),
    (-15.0, 15.0, "BALANCED"),
    (15.0, 40.0, "OPPOSING_MODERATE"),
    (40.0, 100.000001, "OPPOSING_STRONG"),
)


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


def pressure_bucket(value: float) -> str:
    score = float(value)
    for low, high, label in BUCKETS:
        if low <= score < high:
            return label
    return "OPPOSING_STRONG" if score >= 0 else "COUNTER_STRONG"


def opposing_dom_score(*, direction: str, dom_pressure_score: float) -> float:
    """Reorient V191 0-100 pressure around 50 so positive pushes deeper.

    LONG demand is entered by selling pressure, so ASK dominance maps positive.
    SHORT supply is entered by buying pressure, so BID dominance maps positive.
    """
    signed_buyer = max(-100.0, min(100.0, (float(dom_pressure_score) - 50.0) * 2.0))
    return -signed_buyer if str(direction).upper() == "LONG" else signed_buyer


def _outcome_rows(store: SupabaseOperationalStore, *, cutoff: datetime) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,event_type,payload")
        .eq("event_type", OUTCOME_EVENT)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=True)
        .limit(MAX_OUTCOMES)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def _dom_window(
    store: SupabaseOperationalStore,
    *,
    touch_at: datetime,
) -> tuple[dict[str, Any], ...]:
    start = touch_at - timedelta(seconds=DOM_MATCH_BEFORE_SECONDS)
    end = touch_at + timedelta(seconds=DOM_MATCH_AFTER_SECONDS)
    response = (
        store.client.table("xau_dom_pressure_samples")
        .select(
            "observed_at,state,dom_pressure_score,last_imbalance,mean_imbalance,"
            "top5_bid_units,top5_ask_units,bid_top5_change,ask_top5_change,"
            "bid_wall_ratio,ask_wall_ratio,bid_wall_persistence,ask_wall_persistence"
        )
        .gte("observed_at", start.isoformat())
        .lte("observed_at", end.isoformat())
        .order("observed_at", desc=False)
        .execute()
    )
    return tuple(dict(row) for row in (response.data or []))


def choose_touch_dom(
    rows: Sequence[dict[str, Any]],
    *,
    touch_at: datetime,
) -> tuple[dict[str, Any] | None, float | None]:
    samples = [dict(row) for row in rows if _dt(row.get("observed_at")) is not None]
    if not samples:
        return None, None

    # V227 touch time is the opening timestamp of the first M1 touch bar, not
    # intrabar first-tick time. Prefer a sample inside that minute, closest to
    # +30 seconds; otherwise use the closest bounded sample around the bar.
    target = touch_at + timedelta(seconds=30)
    samples.sort(key=lambda row: abs((_dt(row["observed_at"]) - target).total_seconds()))
    chosen = samples[0]
    chosen_at = _dt(chosen.get("observed_at"))

    chronological = sorted(samples, key=lambda row: _dt(row["observed_at"]))
    prior = [
        row for row in chronological
        if chosen_at is not None and _dt(row.get("observed_at")) <= chosen_at
        and _f(row.get("dom_pressure_score")) is not None
    ]
    slope = None
    if len(prior) >= 2:
        first = _f(prior[max(0, len(prior) - 3)].get("dom_pressure_score"))
        last = _f(prior[-1].get("dom_pressure_score"))
        first_at = _dt(prior[max(0, len(prior) - 3)].get("observed_at"))
        last_at = _dt(prior[-1].get("observed_at"))
        if None not in {first, last, first_at, last_at}:
            minutes = max((last_at - first_at).total_seconds() / 60.0, 1e-9)
            slope = (float(last) - float(first)) / minutes
    return chosen, slope


def _episode_from_outcome(
    store: SupabaseOperationalStore,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    payload = dict(row.get("payload") or {})
    touch_at = _dt(payload.get("touch_at"))
    direction = str(payload.get("direction") or "").upper()
    signal_key = str(payload.get("signal_key") or row.get("signal_key") or "")
    parent = dict(payload.get("parent") or {})
    if touch_at is None or direction not in {"LONG", "SHORT"} or not signal_key:
        return None

    dom_rows = _dom_window(store, touch_at=touch_at)
    chosen, slope = choose_touch_dom(dom_rows, touch_at=touch_at)
    if not chosen:
        return None

    dom_score = _f(chosen.get("dom_pressure_score"))
    if dom_score is None:
        return None
    opposing = opposing_dom_score(direction=direction, dom_pressure_score=dom_score)

    turning_depth = _f(payload.get("turning_depth"))
    max_depth = _f(payload.get("max_depth_reached"))
    status = str(payload.get("status") or "UNKNOWN")
    outcome_at = _dt(payload.get("outcome_at"))
    zone_id = str(parent.get("zone_id") or "")
    timeframe = str(parent.get("timeframe") or "H4").upper()

    return {
        "episode_key": f"V227_DOM:{signal_key}",
        "signal_key": signal_key,
        "zone_id": zone_id or None,
        "direction": direction,
        "timeframe": timeframe,
        "first_touch_at": touch_at.isoformat(),
        "outcome_at": None if outcome_at is None else outcome_at.isoformat(),
        "status": status,
        "first_touch_dom_state": str(chosen.get("state") or "UNKNOWN"),
        "first_touch_dom_score": dom_score,
        "first_touch_imbalance": _f(chosen.get("last_imbalance")),
        "dom_pressure_slope": slope,
        "opposing_dom_score": opposing,
        "pressure_bucket": pressure_bucket(opposing),
        "turning_depth": turning_depth,
        "max_depth_reached": max_depth,
        "reaction_hit_050": bool(payload.get("reaction_hit_050")),
        "invalidated": bool(payload.get("invalidated")),
        "zone_low": _f(parent.get("low")),
        "zone_high": _f(parent.get("high")),
        "atr_points": _f(parent.get("atr_points")),
        "metadata": {
            "contract": CONTRACT,
            "dom_source": "CTRADER_OPEN_API_LEVEL_II",
            "dom_scope": "BROKER_VENUE_NOT_CONSOLIDATED_COMEX",
            "touch_time_precision": "V227_M1_TOUCH_BAR",
            "dom_match_window_seconds": {
                "before": DOM_MATCH_BEFORE_SECONDS,
                "after": DOM_MATCH_AFTER_SECONDS,
            },
            "dom_sample_at": chosen.get("observed_at"),
            "mean_imbalance": _f(chosen.get("mean_imbalance")),
            "top5_bid_units": _f(chosen.get("top5_bid_units")),
            "top5_ask_units": _f(chosen.get("top5_ask_units")),
            "bid_top5_change": _f(chosen.get("bid_top5_change")),
            "ask_top5_change": _f(chosen.get("ask_top5_change")),
            "bid_wall_ratio": _f(chosen.get("bid_wall_ratio")),
            "ask_wall_ratio": _f(chosen.get("ask_wall_ratio")),
            "bid_wall_persistence": _f(chosen.get("bid_wall_persistence")),
            "ask_wall_persistence": _f(chosen.get("ask_wall_persistence")),
            "execution_influence": False,
            "execution_authority": False,
        },
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    items = [dict(row) for row in rows]
    result: dict[str, Any] = {}
    for _low, _high, label in BUCKETS:
        selected = [row for row in items if str(row.get("pressure_bucket") or "") == label]
        turning = [
            float(row["turning_depth"])
            for row in selected
            if _f(row.get("turning_depth")) is not None
        ]
        max_depth = [
            float(row["max_depth_reached"])
            for row in selected
            if _f(row.get("max_depth_reached")) is not None
        ]
        holds = sum(bool(row.get("reaction_hit_050")) for row in selected)
        invalid = sum(bool(row.get("invalidated")) for row in selected)
        result[label] = {
            "n": len(selected),
            "hold_050_rate": None if not selected else holds / len(selected),
            "invalid_rate": None if not selected else invalid / len(selected),
            "turning_depth_median": None if not turning else median(turning),
            "max_depth_median": None if not max_depth else median(max_depth),
        }
    return {
        "by_pressure_bucket": result,
        "sample_state": (
            "COLLECTING"
            if len(items) < 30
            else "EARLY"
            if len(items) < 100
            else "MATURE"
        ),
        "episodes": len(items),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_PRESSURE_DEPTH_V247_DEMO_ONLY")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    error: str | None = None
    rows_written = 0
    matched = 0
    summary: dict[str, Any] = {}

    try:
        outcomes = _outcome_rows(store, cutoff=cutoff)
        episode_rows: list[dict[str, Any]] = []
        for row in outcomes:
            episode = _episode_from_outcome(store, row)
            if episode is not None:
                episode_rows.append(episode)
        matched = len(episode_rows)
        if episode_rows:
            store.client.table("xau_pressure_depth_episodes").upsert(
                episode_rows,
                on_conflict="episode_key",
            ).execute()
            rows_written = len(episode_rows)

        response = (
            store.client.table("xau_pressure_depth_episodes")
            .select(
                "pressure_bucket,turning_depth,max_depth_reached,"
                "reaction_hit_050,invalidated"
            )
            .gte("first_touch_at", cutoff.isoformat())
            .execute()
        )
        summary = summarize(tuple(dict(row) for row in (response.data or [])))
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
            "outcomes_scanned": len(_outcome_rows(store, cutoff=cutoff)) if healthy else 0,
            "matched_dom_episodes": matched,
            "rows_upserted": rows_written,
            "summary": summary,
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
        "CTRADER_DEMO_XAU_PRESSURE_DEPTH_PROSPECTIVE "
        f"healthy={healthy} matched={matched} rows={rows_written} "
        f"sample={summary.get('sample_state','NONE')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

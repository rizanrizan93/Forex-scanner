from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import os
from statistics import mean
from typing import Any, Sequence

from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v223_m5_pocket_cluster_selector"
CONTRACT = "XAU_M5_POCKET_CLUSTER_SELECTOR_V223"
SOURCE_WORKER = "ctrader_demo_xau_v222_m5_pocket_quality"

MAX_ACTIVE_AGE_MINUTES = 90.0
CLUSTER_GAP_ATR = 0.10
MAX_CLUSTER_SPAN_ATR = 0.75
MAX_CLUSTER_TIME_GAP_MINUTES = 30.0
MAX_MIDPOINT_SHIFT_ATR = 0.40
PRIMARY_DISTANCE_ATR = 0.50


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


def _clip(value: float, low: float, high: float) -> float:
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


def _gap(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = float(a["low"])
    a_high = float(a["high"])
    b_low = float(b["low"])
    b_high = float(b["high"])
    if min(a_high, b_high) >= max(a_low, b_low):
        return 0.0
    if a_high < b_low:
        return b_low - a_high
    return a_low - b_high


def _distance_to_range(price: float | None, low: float, high: float) -> float | None:
    if price is None:
        return None
    if low <= price <= high:
        return 0.0
    return low - price if price < low else price - high


def _sanitize_family(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        low = _f(row.get("low"))
        high = _f(row.get("high"))
        mapped = _dt(row.get("mapped_at"))
        if low is None or high is None or high < low or mapped is None:
            continue
        row["low"] = low
        row["high"] = high
        row["mapped_at"] = mapped.isoformat()
        output.append(row)
    output.sort(key=lambda row: _dt(row["mapped_at"]) or datetime.max.replace(tzinfo=UTC))
    return output


def cluster_pocket_family(
    rows: Sequence[dict[str, Any]],
    *,
    atr_points: float | None,
) -> list[list[dict[str, Any]]]:
    family = _sanitize_family(rows)
    if not family:
        return []

    atr = None if atr_points in (None, 0) else float(atr_points)
    allowed_gap = 0.0 if atr is None else atr * CLUSTER_GAP_ATR
    max_span = float("inf") if atr is None else atr * MAX_CLUSTER_SPAN_ATR
    max_mid_shift = float("inf") if atr is None else atr * MAX_MIDPOINT_SHIFT_ATR

    clusters: list[list[dict[str, Any]]] = []
    for row in family:
        if not clusters:
            clusters.append([row])
            continue

        cluster = clusters[-1]
        previous = cluster[-1]
        union_low = min(float(item["low"]) for item in cluster)
        union_high = max(float(item["high"]) for item in cluster)
        proposed_low = min(union_low, float(row["low"]))
        proposed_high = max(union_high, float(row["high"]))
        proposed_span = proposed_high - proposed_low

        previous_mapped = _dt(previous.get("mapped_at"))
        row_mapped = _dt(row.get("mapped_at"))
        time_gap_minutes = (
            None
            if previous_mapped is None or row_mapped is None
            else max(0.0, (row_mapped - previous_mapped).total_seconds() / 60.0)
        )
        previous_mid = (float(previous["low"]) + float(previous["high"])) / 2.0
        row_mid = (float(row["low"]) + float(row["high"])) / 2.0
        midpoint_shift = abs(row_mid - previous_mid)

        same_micro_wave = bool(
            _gap(row, {"low": union_low, "high": union_high}) <= allowed_gap
            and proposed_span <= max_span
            and midpoint_shift <= max_mid_shift
            and (
                time_gap_minutes is None
                or time_gap_minutes <= MAX_CLUSTER_TIME_GAP_MINUTES
            )
        )

        if same_micro_wave:
            cluster.append(row)
        else:
            clusters.append([row])

    return clusters


def _cluster_payload(
    rows: Sequence[dict[str, Any]],
    *,
    index: int,
    now: datetime,
    price_now: float | None,
    atr_points: float | None,
) -> dict[str, Any]:
    lows = [float(row["low"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    qualities = [
        float(value)
        for value in (_f(row.get("quality_score_research")) for row in rows)
        if value is not None
    ]
    mapped_times = [
        value for value in (_dt(row.get("mapped_at")) for row in rows)
        if value is not None
    ]

    union_low = min(lows)
    union_high = max(highs)
    core_low = max(lows)
    core_high = min(highs)
    has_consensus_core = core_low <= core_high
    latest_mapped = max(mapped_times) if mapped_times else None
    age_minutes = (
        None
        if latest_mapped is None
        else max(0.0, (now - latest_mapped).total_seconds() / 60.0)
    )
    distance_points = _distance_to_range(price_now, union_low, union_high)
    distance_atr = (
        None
        if distance_points is None or atr_points in (None, 0)
        else distance_points / float(atr_points)
    )

    late_count = sum(
        str(row.get("timing_state") or "") == "LATE_FOR_FIRST_ENTRY_WAIT_RETEST"
        for row in rows
    )
    touched_count = sum(
        str(row.get("timing_state") or "") == "POST_MAP_TOUCH_CONFIRMED"
        for row in rows
    )
    active_count = len(rows) - late_count
    latest = dict(rows[-1])

    if age_minutes is not None and age_minutes > MAX_ACTIVE_AGE_MINUTES:
        role = "HISTORICAL_CLUSTER"
    elif late_count == len(rows):
        role = "RETEST_ONLY_CLUSTER"
    elif touched_count > 0:
        role = "PROVEN_RETEST_CLUSTER"
    elif distance_atr is not None and distance_atr <= PRIMARY_DISTANCE_ATR:
        role = "ACTIVE_WATCH_CLUSTER"
    else:
        role = "PREMAPPED_CLUSTER"

    mean_quality = None if not qualities else mean(qualities)
    max_quality = None if not qualities else max(qualities)
    recency_component = (
        0.0
        if age_minutes is None
        else _clip(1.0 - age_minutes / MAX_ACTIVE_AGE_MINUTES, 0.0, 1.0)
    )
    distance_component = (
        0.0
        if distance_atr is None
        else _clip(1.0 - distance_atr / PRIMARY_DISTANCE_ATR, 0.0, 1.0)
    )
    quality_component = 0.0 if mean_quality is None else _clip(mean_quality / 100.0, 0.0, 1.0)
    stability_component = _clip(min(len(rows), 3) / 3.0, 0.0, 1.0)
    late_penalty = late_count / max(1, len(rows))

    selector_score = 100.0 * (
        0.40 * quality_component
        + 0.25 * recency_component
        + 0.20 * distance_component
        + 0.15 * stability_component
        - 0.20 * late_penalty
    )
    selector_score = round(_clip(selector_score, 0.0, 100.0), 2)

    return {
        "cluster_id": f"V223_CLUSTER_{index:02d}",
        "direction": latest.get("direction"),
        "role": role,
        "count": len(rows),
        "active_member_count": active_count,
        "late_member_count": late_count,
        "post_map_touch_member_count": touched_count,
        "union_zone": {"low": union_low, "high": union_high},
        "consensus_core": (
            {"low": core_low, "high": core_high}
            if has_consensus_core else {}
        ),
        "has_consensus_core": has_consensus_core,
        "first_mapped_at": min(mapped_times).isoformat() if mapped_times else None,
        "latest_mapped_at": latest_mapped.isoformat() if latest_mapped else None,
        "age_minutes": age_minutes,
        "price_reference": price_now,
        "distance_points": distance_points,
        "distance_atr": distance_atr,
        "mean_quality_research": mean_quality,
        "max_quality_research": max_quality,
        "selector_score_research": selector_score,
        "latest_timing_state": latest.get("timing_state"),
        "latest_signal_key": latest.get("signal_key"),
        "members": [dict(row) for row in rows],
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def select_clusters(
    evaluation: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    family = [dict(row) for row in list(evaluation.get("family") or [])]
    parent = dict(evaluation.get("parent_context") or {})
    atr = _f(parent.get("atr_points"))
    price_now = _f(evaluation.get("current_price_reference"))
    clusters = cluster_pocket_family(family, atr_points=atr)

    payloads = [
        _cluster_payload(
            cluster,
            index=index,
            now=now,
            price_now=price_now,
            atr_points=atr,
        )
        for index, cluster in enumerate(clusters, start=1)
    ]

    primary_pool = [
        row
        for row in payloads
        if row["role"] == "ACTIVE_WATCH_CLUSTER"
        and (row.get("age_minutes") is None or float(row["age_minutes"]) <= MAX_ACTIVE_AGE_MINUTES)
        and (row.get("distance_atr") is None or float(row["distance_atr"]) <= PRIMARY_DISTANCE_ATR)
    ]
    primary_pool.sort(
        key=lambda row: (
            -float(row.get("selector_score_research") or 0.0),
            float(row.get("distance_atr") or 0.0),
        )
    )
    primary = dict(primary_pool[0]) if primary_pool else {}

    alternative_pool = [
        row for row in primary_pool
        if row.get("cluster_id") != primary.get("cluster_id")
    ]
    alternative = dict(alternative_pool[0]) if alternative_pool else {}

    retest_only = [
        dict(row) for row in payloads if row["role"] == "RETEST_ONLY_CLUSTER"
    ]
    proven_retest = [
        dict(row) for row in payloads if row["role"] == "PROVEN_RETEST_CLUSTER"
    ]
    historical = [
        dict(row) for row in payloads if row["role"] == "HISTORICAL_CLUSTER"
    ]

    return {
        "contract": CONTRACT,
        "state": "CLUSTER_MAP_AVAILABLE" if payloads else "NO_CLUSTER_MAP",
        "direction": evaluation.get("direction"),
        "price_reference": price_now,
        "parent_context": parent,
        "primary_cluster": primary,
        "alternative_cluster": alternative,
        "retest_only_clusters": retest_only,
        "proven_retest_clusters": proven_retest,
        "historical_clusters": historical,
        "clusters": payloads,
        "selection_policy": {
            "max_active_age_minutes": MAX_ACTIVE_AGE_MINUTES,
            "cluster_gap_atr": CLUSTER_GAP_ATR,
            "max_cluster_span_atr": MAX_CLUSTER_SPAN_ATR,
            "max_cluster_time_gap_minutes": MAX_CLUSTER_TIME_GAP_MINUTES,
            "max_midpoint_shift_atr": MAX_MIDPOINT_SHIFT_ATR,
            "micro_wave_cluster_count": len(payloads),
            "note": (
                "V223 clusters overlapping/nearby M5 pocket episodes only while they remain "
                "inside one bounded micro-wave. Time gaps, excessive union span, or a large "
                "midpoint jump start a new cluster so chained sweep origins cannot merge into "
                "one oversized area. Consensus core is research geometry only, not an entry order."
            ),
        },
        "interpretation": (
            "PRIMARY means the highest-ranked currently relevant pocket cluster for "
            "research/watch purposes. RETEST_ONLY means the first-entry opportunity is "
            "already considered late. Micro-wave segmentation prevents older pocket chains "
            "from swallowing a newer stable area. V223 has no execution or promotion authority."
        ),
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V223_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V223_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    evaluation: dict[str, Any] = {}
    error: str | None = None

    try:
        source = _latest_heartbeat(store, SOURCE_WORKER)
        source_eval = dict(dict(source.get("details") or {}).get("evaluation") or {})
        evaluation = select_clusters(source_eval, now=now)
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
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": now.isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V223_M5_POCKET_CLUSTER_SELECTOR "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} "
        f"clusters={len(evaluation.get('clusters') or [])} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

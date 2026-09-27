from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime
from typing import Any, Sequence

import pandas as pd

from .models import Bar, ensure_utc
from .research_xau_htf_strategic_regime_v180 import (
    STRONG_SWITCH_THRESHOLD,
    RegimePoint,
    build_regime_points,
)
from .research_xau_v229_historical_v242 import (
    ARTIFACT_CONTRACT as V242_ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RESEARCH_VERSION as V242_RESEARCH_VERSION,
    simulate_year as simulate_v242_year,
)

RESEARCH_VERSION = "XAU_V229_REGIME_ADMISSION_V243_1"
ARTIFACT_CONTRACT = "XAU_V229_REGIME_ADMISSION_V243_1_EVIDENCE_1"
SYMBOL = "XAUUSD"

# Frozen, pre-registered ablations. No parameter search is performed in V243.
VARIANT_IDS = (
    "ALL_BASELINE",
    "REGIME_ALIGNED",
    "REGIME_ALIGNED_STRONG",
    "H4_SOURCE_ONLY",
    "REGIME_ALIGNED_H4_SOURCE",
    "REGIME_ALIGNED_PRETOUCH",
    "REGIME_ALIGNED_CONFIRMATION",
    "REGIME_ALIGNED_H4_PRETOUCH",
    "REGIME_ALIGNED_H4_CONFIRMATION",
)


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return ensure_utc(parsed)


def _m15_bars(price_m1: pd.DataFrame) -> tuple[Bar, ...]:
    work = price_m1.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    frame = (
        work.set_index("timestamp")
        .resample("15min", label="right", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )
    return tuple(
        Bar(
            symbol=SYMBOL,
            timeframe="M15",
            timestamp=ensure_utc(pd.Timestamp(row["timestamp"]).to_pydatetime()),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_count=1,
            spread_avg=0.0,
            spread_max=0.0,
        )
        for _, row in frame.iterrows()
    )


def _latest_regime(
    points: Sequence[RegimePoint],
    timestamps: Sequence[datetime],
    at: datetime,
) -> RegimePoint | None:
    index = bisect_right(timestamps, ensure_utc(at)) - 1
    return None if index < 0 else points[index]


def _regime_payload(point: RegimePoint | None, *, direction: str) -> dict[str, Any]:
    if point is None:
        return {
            "regime_available": False,
            "strategic_bias": None,
            "raw_direction": None,
            "raw_score": None,
            "strong_regime": False,
            "alignment": "NO_REGIME",
            "regime_map_at": None,
        }
    bias = str(point.strategic_bias or "").upper()
    side = str(direction or "").upper()
    if bias not in {"LONG", "SHORT"}:
        alignment = "NEUTRAL"
    elif bias == side:
        alignment = "ALIGNED"
    else:
        alignment = "COUNTER"
    return {
        "regime_available": True,
        "strategic_bias": bias,
        "raw_direction": str(point.raw_direction or "").upper(),
        "raw_score": float(point.raw_score),
        "strong_regime": abs(float(point.raw_score)) >= float(STRONG_SWITCH_THRESHOLD),
        "alignment": alignment,
        "regime_map_at": ensure_utc(point.map_at).isoformat(),
    }


def attach_v180_regime(
    *,
    price_m1: pd.DataFrame,
    result: dict[str, Any],
) -> dict[str, Any]:
    bars = _m15_bars(price_m1)
    points = build_regime_points(bars)
    times = tuple(ensure_utc(point.map_at) for point in points)

    plans = []
    plan_meta: dict[str, dict[str, Any]] = {}
    for raw in list(result.get("plans") or []):
        plan = dict(raw)
        plan_at = _dt(plan.get("plan_at"))
        direction = str(plan.get("direction") or "").upper()
        point = None if plan_at is None else _latest_regime(points, times, plan_at)
        meta = _regime_payload(point, direction=direction)
        enriched = {**plan, **meta}
        plans.append(enriched)
        plan_meta[str(plan.get("plan_id") or "")] = meta

    trades = []
    for raw in list(result.get("trades") or []):
        trade = dict(raw)
        meta = dict(plan_meta.get(str(trade.get("plan_id") or "")) or {})
        trades.append({**trade, **meta})

    counts: dict[str, int] = {}
    for plan in plans:
        key = str(plan.get("alignment") or "NO_REGIME")
        counts[key] = counts.get(key, 0) + 1

    return {
        **result,
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "upstream_v242_research_version": V242_RESEARCH_VERSION,
        "upstream_v242_artifact_contract": V242_ARTIFACT_CONTRACT,
        "plans": plans,
        "trades": trades,
        "regime_point_count": len(points),
        "plan_regime_alignment_counts": counts,
        "regime_contract": {
            "engine": "XAU_HTF_STRATEGIC_REGIME_V180",
            "inputs": "COMPLETED_D1_H4_ONLY",
            "strong_threshold": float(STRONG_SWITCH_THRESHOLD),
            "join_rule": "LATEST_V180_MAP_AT_LE_PLAN_AT",
            "lookahead_allowed": False,
        },
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> dict[str, Any]:
    base = simulate_v242_year(price_m1, target_year=target_year)
    return attach_v180_regime(price_m1=price_m1, result=base)


def variant_match(row: dict[str, Any], variant_id: str) -> bool:
    variant = str(variant_id).upper()
    if variant not in VARIANT_IDS:
        raise ValueError(f"V243_UNKNOWN_VARIANT:{variant_id}")

    alignment = str(row.get("alignment") or "").upper()
    source = str(row.get("candidate_source") or "").upper()
    slot = int(row.get("slot") or 0)
    strong = bool(row.get("strong_regime"))

    if variant == "ALL_BASELINE":
        return True
    if variant == "REGIME_ALIGNED":
        return alignment == "ALIGNED"
    if variant == "REGIME_ALIGNED_STRONG":
        return alignment == "ALIGNED" and strong
    if variant == "H4_SOURCE_ONLY":
        return source == "H4"
    if variant == "REGIME_ALIGNED_H4_SOURCE":
        return alignment == "ALIGNED" and source == "H4"
    if variant == "REGIME_ALIGNED_PRETOUCH":
        return alignment == "ALIGNED" and slot in {1, 2}
    if variant == "REGIME_ALIGNED_CONFIRMATION":
        return alignment == "ALIGNED" and slot in {3, 4}
    if variant == "REGIME_ALIGNED_H4_PRETOUCH":
        return alignment == "ALIGNED" and source == "H4" and slot in {1, 2}
    if variant == "REGIME_ALIGNED_H4_CONFIRMATION":
        return alignment == "ALIGNED" and source == "H4" and slot in {3, 4}
    return False

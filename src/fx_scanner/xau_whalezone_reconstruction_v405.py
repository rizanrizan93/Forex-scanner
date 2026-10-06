from __future__ import annotations

"""V405 behavioral reconstruction of tiered XAUUSD reaction zones.

This module reconstructs the *observable behavior* of a tiered zone map from
causal scanner geometry. It does not claim access to, or reproduction of, any
proprietary indicator formula.

Design goals:
- show nearby BUY and SELL reaction areas even when no entry is active;
- rank several zones on each side instead of collapsing the map to one zone;
- preserve H4/H1 structural context while allowing a nearer local/SR zone to
  become tier 1;
- attach liquidity and lifecycle metadata for later M15/M5 validation;
- remain decision-support only. Broker execution authority is deliberately
  outside this module.
"""

from math import isfinite
from typing import Any

from .xau_simple_reversal_engine_v390 import (
    PREPARE_DISTANCE_ATR,
    _collect_candidates,
    _estimate_atr,
    _readiness,
)

CONTRACT = "XAU_RIZAN_WHALEZONE_RECONSTRUCTION_V405"
MODE = "BEHAVIORAL_RECONSTRUCTION"
MAX_TIERS_PER_SIDE = 3


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _overlap(a: dict[str, Any], b: dict[str, Any], *, tolerance: float) -> bool:
    alo, ahi = _f(a.get("low")), _f(a.get("high"))
    blo, bhi = _f(b.get("low")), _f(b.get("high"))
    if None in {alo, ahi, blo, bhi}:
        return False
    assert alo is not None and ahi is not None and blo is not None and bhi is not None
    return not (ahi + tolerance < blo or bhi + tolerance < alo)


def _merge_cluster(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge near-duplicate geometry while preserving the strongest metadata."""
    ordered = sorted(rows, key=lambda row: float(row.get("score") or 0.0), reverse=True)
    best = dict(ordered[0])
    lows = [float(row["low"]) for row in ordered if _f(row.get("low")) is not None]
    highs = [float(row["high"]) for row in ordered if _f(row.get("high")) is not None]
    best["low"] = min(lows)
    best["high"] = max(highs)
    best["center"] = (best["low"] + best["high"]) / 2.0
    best["merged_sources"] = [
        {
            "source_type": row.get("source_type"),
            "timeframe": row.get("timeframe"),
            "zone_id": row.get("zone_id"),
            "score": row.get("score"),
        }
        for row in ordered
    ]
    liquidity: list[dict[str, Any]] = []
    seen_liq: set[tuple[str, float]] = set()
    for row in ordered:
        for raw in list(row.get("liquidity") or []):
            item = _d(raw)
            px = _f(item.get("price"))
            if px is None:
                continue
            key = (str(item.get("side") or "").upper(), round(px, 4))
            if key in seen_liq:
                continue
            seen_liq.add(key)
            liquidity.append(item)
    best["liquidity"] = liquidity[:6]
    return best


def _dedupe(rows: list[dict[str, Any]], *, atr: float) -> list[dict[str, Any]]:
    """Cluster overlapping/near-identical SR and S/D candidates."""
    tolerance = max(0.05 * atr, 0.50)
    clusters: list[list[dict[str, Any]]] = []
    for raw in rows:
        row = dict(raw)
        for cluster in clusters:
            if _overlap(row, cluster[0], tolerance=tolerance):
                cluster.append(row)
                break
        else:
            clusters.append([row])
    return [_merge_cluster(cluster) for cluster in clusters]


def _structural_priority(row: dict[str, Any]) -> float:
    """Secondary ranking: quality first, then structural persistence."""
    score = float(row.get("score") or 0.0)
    tf = str(row.get("timeframe") or "").upper()
    source = str(row.get("source_type") or "").upper()
    life = str(row.get("lifecycle_state") or "").upper()
    if tf == "H4":
        score += 2.5
    elif tf == "H1":
        score += 2.0
    if source == "SD":
        score += 0.75
    if "CONFIRMED" in life or "RETEST" in life:
        score += 1.0
    touch_count = _f(row.get("touch_count"))
    if touch_count is not None and touch_count >= 3:
        score -= min(2.0, 0.5 * (touch_count - 2.0))
    return score


def _tier_rows(
    rows: list[dict[str, Any]],
    *,
    direction: str,
    price: float,
    atr: float,
    limit: int = MAX_TIERS_PER_SIDE,
) -> list[dict[str, Any]]:
    """Return outward tiers from current price: tier 1 nearest, then deeper HTF."""
    deduped = _dedupe(rows, atr=atr)
    eligible: list[dict[str, Any]] = []
    for row in deduped:
        low = _f(row.get("low"))
        high = _f(row.get("high"))
        if low is None or high is None or high <= low:
            continue
        center = (low + high) / 2.0
        if direction == "LONG" and center > price + 0.20 * atr:
            continue
        if direction == "SHORT" and center < price - 0.20 * atr:
            continue
        distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
        item = dict(row)
        item["distance_points"] = distance
        item["distance_atr"] = distance / atr if atr > 0 else None
        item["structural_priority"] = round(_structural_priority(item), 4)
        item["readiness"] = _readiness(item, price=price, atr=atr)
        eligible.append(item)

    eligible.sort(
        key=lambda row: (
            float(row.get("distance_atr") or 0.0),
            -float(row.get("structural_priority") or 0.0),
            -float(row.get("score") or 0.0),
        )
    )

    selected: list[dict[str, Any]] = []
    for row in eligible:
        if len(selected) >= int(limit):
            break
        item = dict(row)
        tier = len(selected) + 1
        item["tier"] = tier
        item["label"] = f"{'BUY' if direction == 'LONG' else 'SELL'}_{tier}"
        selected.append(item)
    return selected


def _side_state(zones: list[dict[str, Any]], *, price: float, atr: float) -> str:
    if not zones:
        return "UNAVAILABLE"
    first = zones[0]
    readiness = str(first.get("readiness") or "WAIT").upper()
    if readiness == "READY_EARLY":
        return "IN_ZONE_EARLY"
    if readiness == "WATCH_REACTION":
        return "IN_ZONE_WATCH"
    if readiness == "PREPARE":
        return "APPROACHING"
    distance = _f(first.get("distance_atr"))
    if distance is not None and distance <= PREPARE_DISTANCE_ATR:
        return "APPROACHING"
    return "MAPPED"


def _range_state(
    buy_zones: list[dict[str, Any]],
    sell_zones: list[dict[str, Any]],
    *,
    price: float,
) -> dict[str, Any]:
    if not buy_zones or not sell_zones:
        return {"state": "ONE_SIDED_MAP"}
    floor = _f(buy_zones[0].get("high"))
    ceiling = _f(sell_zones[0].get("low"))
    if floor is None or ceiling is None or floor >= ceiling:
        return {"state": "OVERLAPPING_REACTION_ZONES"}
    width = ceiling - floor
    position = (price - floor) / width if width > 0 else None
    if position is None:
        location = "UNKNOWN"
    elif position <= 0.33:
        location = "LOWER_THIRD"
    elif position >= 0.67:
        location = "UPPER_THIRD"
    else:
        location = "MID_RANGE"
    return {
        "state": "LOCAL_RANGE",
        "floor": floor,
        "ceiling": ceiling,
        "mid": (floor + ceiling) / 2.0,
        "width_points": width,
        "price_location": location,
    }


def _focus(
    buy_zones: list[dict[str, Any]],
    sell_zones: list[dict[str, Any]],
) -> tuple[str, str]:
    buy_state = str(buy_zones[0].get("readiness") or "WAIT").upper() if buy_zones else "NONE"
    sell_state = str(sell_zones[0].get("readiness") or "WAIT").upper() if sell_zones else "NONE"
    active = {"READY_EARLY", "WATCH_REACTION", "PREPARE"}
    if buy_state in active and sell_state not in active:
        return "LONG", f"BUY_1_{buy_state}"
    if sell_state in active and buy_state not in active:
        return "SHORT", f"SELL_1_{sell_state}"
    if buy_state in active and sell_state in active:
        buy_distance = _f(buy_zones[0].get("distance_atr")) or 999.0
        sell_distance = _f(sell_zones[0].get("distance_atr")) or 999.0
        if buy_distance < sell_distance:
            return "LONG", "BOTH_ACTIVE_BUY_1_NEARER"
        if sell_distance < buy_distance:
            return "SHORT", "BOTH_ACTIVE_SELL_1_NEARER"
        return "WAIT", "BOTH_ACTIVE_EQUIDISTANT"
    return "WAIT", "MAP_ONLY_NO_ACTIVE_EDGE"


def evaluate_whalezone_reconstruction_v405(
    sd_eval: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build causal BUY/SELL tiers from the current scanner S/D snapshot."""
    sd = _d(sd_eval)
    price = _f(sd.get("price_now"))
    if price is None:
        return {
            "contract": CONTRACT,
            "mode": MODE,
            "state": "UNAVAILABLE",
            "direction": "WAIT",
            "reason": "PRICE_UNAVAILABLE",
            "buy_zones": [],
            "sell_zones": [],
            "execution_authority": False,
            "demo_auto_execution": False,
            "live_execution_enabled": False,
            "proprietary_formula_claimed": False,
        }

    atr = _estimate_atr(sd)
    long_rows = _collect_candidates(sd, direction="LONG", price=price, atr=atr)
    short_rows = _collect_candidates(sd, direction="SHORT", price=price, atr=atr)
    buy_zones = _tier_rows(long_rows, direction="LONG", price=price, atr=atr)
    sell_zones = _tier_rows(short_rows, direction="SHORT", price=price, atr=atr)
    direction, reason = _focus(buy_zones, sell_zones)
    range_payload = _range_state(buy_zones, sell_zones, price=price)

    if direction == "LONG":
        state = "FOCUS_BUY_1"
    elif direction == "SHORT":
        state = "FOCUS_SELL_1"
    elif buy_zones or sell_zones:
        state = "RANGE_MAP"
    else:
        state = "NO_VALID_ZONES"

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": state,
        "direction": direction,
        "reason": reason,
        "price_now": price,
        "atr_reference": atr,
        "buy_state": _side_state(buy_zones, price=price, atr=atr),
        "sell_state": _side_state(sell_zones, price=price, atr=atr),
        "buy_zones": buy_zones,
        "sell_zones": sell_zones,
        "range": range_payload,
        "confirmation_model": {
            "structure_timeframes": ["H4", "H1"],
            "validation_timeframe": "M15",
            "refinement_timeframe": "M5",
            "solid_close_outside_zone_invalidates": True,
            "wick_sweep_alone_invalidates": False,
            "note": "M15 close/acceptance semantics are a reconstruction hypothesis and require candle data before runtime enforcement.",
        },
        "reconstruction_basis": "USER_SHARED_VISUAL_PATTERN_PLUS_EXISTING_CAUSAL_SD_SR_LIQUIDITY_GEOMETRY",
        "proprietary_formula_claimed": False,
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "validation_status": "BEHAVIORAL_RECONSTRUCTION_REQUIRES_INDEPENDENT_REPLAY_AND_FORWARD_VALIDATION",
    }


__all__ = [
    "CONTRACT",
    "MODE",
    "evaluate_whalezone_reconstruction_v405",
]

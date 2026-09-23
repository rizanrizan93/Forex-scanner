from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .models import ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

CONTRACT = "XAU_AFIC_SUPPLY_DEMAND_CONTEXT_V1"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
MAX_ATLAS_AGE_MINUTES = 20
NEAR_SAME_DIRECTION_ATR = 0.50
NEAR_OPPOSITE_ATR = 0.75


def _dt(value: Any) -> datetime | None:
    if value is None:
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


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = _finite(a.get("low"))
    a_high = _finite(a.get("high"))
    b_low = _finite(b.get("low"))
    b_high = _finite(b.get("high"))
    if None in {a_low, a_high, b_low, b_high}:
        return 0.0
    assert a_low is not None and a_high is not None
    assert b_low is not None and b_high is not None
    if a_low >= a_high or b_low >= b_high:
        return 0.0
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    denominator = max(min(a_high - a_low, b_high - b_low), 1e-12)
    return overlap / denominator


def _distance_between(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    a_low = _finite(a.get("low"))
    a_high = _finite(a.get("high"))
    b_low = _finite(b.get("low"))
    b_high = _finite(b.get("high"))
    if None in {a_low, a_high, b_low, b_high}:
        return None
    assert a_low is not None and a_high is not None
    assert b_low is not None and b_high is not None
    if a_high >= b_low and b_high >= a_low:
        return 0.0
    if a_high < b_low:
        return b_low - a_high
    return a_low - b_high


def _distance_to_price(zone: dict[str, Any], price: float | None) -> float | None:
    low = _finite(zone.get("low"))
    high = _finite(zone.get("high"))
    if low is None or high is None or price is None:
        return None
    if low <= price <= high:
        return 0.0
    if price < low:
        return low - price
    return price - high


def _compact_zone(zone: dict[str, Any] | None) -> dict[str, Any] | None:
    if not zone:
        return None
    keys = (
        "zone_id",
        "timeframe",
        "zone_class",
        "pattern",
        "direction",
        "low",
        "high",
        "proximal",
        "distal",
        "status",
        "age_bucket",
        "age_hours",
        "distance_points",
        "distance_atr",
        "atr_points",
        "research_score",
        "strategic_alignment",
        "session_context",
        "htf_nesting_count",
        "execution_authority",
        "execution_influence",
    )
    payload = {key: zone.get(key) for key in keys if key in zone}
    payload["lifecycle"] = dict(zone.get("lifecycle") or {})
    payload["approach"] = dict(zone.get("approach") or {})
    payload["liquidity"] = dict(zone.get("liquidity") or {})
    payload["nested_in"] = list(zone.get("nested_in") or [])
    return payload


def latest_atlas(
    store: SupabaseOperationalStore,
) -> tuple[datetime | None, dict[str, Any]]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", ATLAS_WORKER)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    details = dict(row.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    return _dt(row.get("observed_at")), evaluation


def attach_supply_demand_context(
    store: SupabaseOperationalStore,
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    out = dict(payload)
    heartbeat_at, atlas = latest_atlas(store)
    now = ensure_utc(observed_at)
    atlas_age_minutes = (
        None
        if heartbeat_at is None
        else max(0.0, (now - heartbeat_at).total_seconds() / 60.0)
    )
    stale = bool(
        heartbeat_at is None
        or atlas_age_minutes is None
        or atlas_age_minutes > MAX_ATLAS_AGE_MINUTES
    )

    continuation = str(out.get("continuation_direction") or "").upper()
    first_leg = str(out.get("first_leg_direction") or "").upper()
    canonical = dict(out.get("zone") or {})
    nearest_demand = _compact_zone(dict(atlas.get("nearest_demand") or {}))
    nearest_supply = _compact_zone(dict(atlas.get("nearest_supply") or {}))
    path_map = dict(atlas.get("path_map") or {})
    demand_to_supply = dict(path_map.get("demand_to_supply") or {})
    supply_to_demand = dict(path_map.get("supply_to_demand") or {})
    active_path = dict(path_map.get("active_path") or {})
    first_leg_path = (
        demand_to_supply
        if first_leg == "LONG"
        else supply_to_demand
        if first_leg == "SHORT"
        else {}
    )
    continuation_path = (
        demand_to_supply
        if continuation == "LONG"
        else supply_to_demand
        if continuation == "SHORT"
        else {}
    )
    last_price = _finite(atlas.get("last_closed_m15_price"))
    if last_price is None:
        last_price = _finite(out.get("map_price"))

    if continuation == "LONG":
        same_direction = nearest_demand
        opposite_direction = nearest_supply
    elif continuation == "SHORT":
        same_direction = nearest_supply
        opposite_direction = nearest_demand
    else:
        same_direction = None
        opposite_direction = None

    canonical_atr = _finite(canonical.get("h1_atr"))
    same_overlap = (
        0.0
        if not canonical or same_direction is None
        else _overlap_ratio(canonical, same_direction)
    )
    same_distance = (
        None
        if not canonical or same_direction is None
        else _distance_between(canonical, same_direction)
    )
    same_distance_atr = (
        None
        if same_distance is None or canonical_atr is None or canonical_atr <= 0
        else same_distance / canonical_atr
    )
    opposite_price_distance = (
        None
        if opposite_direction is None
        else _distance_to_price(opposite_direction, last_price)
    )
    opposite_atr = (
        None
        if opposite_direction is None
        else _finite(opposite_direction.get("atr_points"))
    )
    opposite_price_distance_atr = (
        None
        if opposite_price_distance is None or opposite_atr is None or opposite_atr <= 0
        else opposite_price_distance / opposite_atr
    )

    same_supported = bool(
        same_direction is not None
        and (
            same_overlap > 0
            or (
                same_distance_atr is not None
                and same_distance_atr <= NEAR_SAME_DIRECTION_ATR
            )
        )
    )
    opposite_near = bool(
        opposite_direction is not None
        and opposite_price_distance_atr is not None
        and opposite_price_distance_atr <= NEAR_OPPOSITE_ATR
    )

    if stale:
        state = "ATLAS_STALE_NO_POLICY_EFFECT"
    elif canonical and same_overlap > 0:
        state = "CANONICAL_OVERLAPS_SUPPLY_DEMAND"
    elif canonical and same_supported:
        state = "CANONICAL_NEAR_SAME_DIRECTION_SUPPLY_DEMAND"
    elif canonical and opposite_near:
        state = "CANONICAL_WITH_NEAR_OPPOSITE_REVERSAL_ZONE"
    elif canonical:
        state = "CANONICAL_WITHOUT_NEAR_SUPPLY_DEMAND_CONFLUENCE"
    elif same_direction is not None or opposite_direction is not None:
        state = "NO_CANONICAL_ZONE_SUPPLY_DEMAND_PREPARE_ONLY"
    else:
        state = "NO_SUPPLY_DEMAND_CONTEXT"

    context = {
        "contract": CONTRACT,
        "state": state,
        "atlas_worker": ATLAS_WORKER,
        "atlas_observed_at": None if heartbeat_at is None else heartbeat_at.isoformat(),
        "atlas_age_minutes": atlas_age_minutes,
        "atlas_stale": stale,
        "atlas_state": atlas.get("state"),
        "last_closed_m15_price": last_price,
        "session_context": atlas.get("session_context"),
        "continuation_direction": continuation or None,
        "first_leg_direction": first_leg or None,
        "canonical_zone_present": bool(canonical),
        "canonical_zone_id": canonical.get("zone_id"),
        "same_direction_zone": same_direction,
        "opposite_reversal_zone": opposite_direction,
        "same_direction_overlap_ratio": same_overlap,
        "same_direction_distance_atr": same_distance_atr,
        "same_direction_confluence": same_supported,
        "opposite_zone_near_price": opposite_near,
        "opposite_zone_distance_atr": opposite_price_distance_atr,
        "path_contract": path_map.get("contract"),
        "first_leg_path": first_leg_path,
        "continuation_path": continuation_path,
        "active_reaction_path": active_path,
        "prepare_only_fallback": bool(not canonical and not stale),
        "required_for_execution": False,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "Supply/demand is AFIC context and preparation evidence only. "
            "Path mapping can identify the next opposing zone and internal waypoints, "
            "but it cannot create or upgrade execution authority."
        ),
    }
    out["supply_demand_context"] = context
    return out


def context_token(payload: dict[str, Any]) -> tuple[str, ...]:
    context = dict(payload.get("supply_demand_context") or {})
    same = dict(context.get("same_direction_zone") or {})
    opposite = dict(context.get("opposite_reversal_zone") or {})
    first_leg_path = dict(context.get("first_leg_path") or {})
    primary_target = dict(first_leg_path.get("primary_opposing_zone") or {})
    return (
        str(context.get("state") or "NONE"),
        str(context.get("atlas_observed_at") or "NONE"),
        str(same.get("zone_id") or "NONE"),
        str(opposite.get("zone_id") or "NONE"),
        str(context.get("same_direction_confluence") or False),
        str(context.get("opposite_zone_near_price") or False),
        str(first_leg_path.get("state") or "NONE"),
        str(primary_target.get("zone_id") or "NONE"),
    )

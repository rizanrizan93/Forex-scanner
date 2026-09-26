from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from .models import ensure_utc
from .demo_xau_v226_rizan_depth_map import _runtime_m15_zones
from .storage.supabase_operational import SupabaseOperationalStore

CONTRACT = "XAU_AFIC_SUPPLY_DEMAND_CONTEXT_V1"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
DOM_WORKER = "ctrader_demo_xau_dom_v191"
EVENT_RISK_WORKER = "ctrader_demo_xau_event_risk_v192"
MAX_ATLAS_AGE_MINUTES = 20
MAX_DOM_AGE_MINUTES = 3
MAX_EVENT_RISK_AGE_MINUTES = 10
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
        .order("observed_at", desc=True)
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


def latest_dom(
    store: SupabaseOperationalStore,
) -> tuple[datetime | None, dict[str, Any]]:
    if not hasattr(store, "client"):
        return None, {}
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", DOM_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    details = dict(row.get("details") or {})
    analysis = dict(details.get("analysis") or {})
    return _dt(row.get("observed_at")), analysis


def latest_event_risk(
    store: SupabaseOperationalStore,
) -> tuple[datetime | None, dict[str, Any]]:
    if not hasattr(store, "client"):
        return None, {}
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", EVENT_RISK_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    if not rows:
        return None, {}
    row = dict(rows[0])
    return _dt(row.get("observed_at")), dict(row.get("details") or {})


def attach_supply_demand_context(
    store: SupabaseOperationalStore,
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    out = dict(payload)
    heartbeat_at, atlas = latest_atlas(store)
    dom_heartbeat_at, dom = latest_dom(store)
    event_heartbeat_at, event_details = latest_event_risk(store)
    event_risk = dict(event_details.get("risk") or {})
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

    dom_age_minutes = (
        None
        if dom_heartbeat_at is None
        else max(0.0, (now - dom_heartbeat_at).total_seconds() / 60.0)
    )
    dom_stale = bool(
        dom_heartbeat_at is None
        or dom_age_minutes is None
        or dom_age_minutes > MAX_DOM_AGE_MINUTES
    )

    event_age_minutes = (
        None
        if event_heartbeat_at is None
        else max(0.0, (now - event_heartbeat_at).total_seconds() / 60.0)
    )
    event_stale = bool(
        event_heartbeat_at is None
        or event_age_minutes is None
        or event_age_minutes > MAX_EVENT_RISK_AGE_MINUTES
    )
    event_state = (
        "EVENT_RISK_STALE_NO_EFFECT"
        if event_stale
        else str(event_risk.get("state") or "CLEAR")
    )

    continuation = str(out.get("continuation_direction") or "").upper()
    first_leg = str(out.get("first_leg_direction") or "").upper()
    canonical = dict(out.get("zone") or {})
    nearest_demand = _compact_zone(dict(atlas.get("nearest_demand") or {}))
    nearest_supply = _compact_zone(dict(atlas.get("nearest_supply") or {}))
    path_map = dict(atlas.get("path_map") or {})
    micro_refinement = dict(
        atlas.get("micro_refinement")
        or path_map.get("micro_refinement")
        or {}
    )
    m5_path_projection = dict(
        atlas.get("m5_path_projection")
        or path_map.get("m5_path_projection")
        or {}
    )
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
    active_path_source = dict(active_path.get("source_zone") or {})
    first_leg_source = dict(first_leg_path.get("source_zone") or {})
    path_overlap_ratio = (
        0.0
        if not active_path_source or not first_leg_source
        else _overlap_ratio(active_path_source, first_leg_source)
    )
    path_direction_conflict = bool(
        active_path
        and first_leg_path
        and str(active_path.get("reaction_direction") or "").upper()
        != str(first_leg_path.get("reaction_direction") or "").upper()
        and str(active_path_source.get("timeframe") or "").upper() == "H1"
        and str(first_leg_source.get("timeframe") or "").upper() == "H1"
        and path_overlap_ratio >= 0.25
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

    runtime_m15_zones = _runtime_m15_zones(
        list(atlas.get("chart_bars_m15") or [])
    )
    wanted_target_direction = (
        "SHORT" if continuation == "LONG"
        else "LONG" if continuation == "SHORT"
        else ""
    )
    m15_target_zones = [
        dict(zone)
        for zone in runtime_m15_zones
        if str(zone.get("direction") or "").upper() == wanted_target_direction
    ]
    m15_target_zones.sort(
        key=lambda zone: (
            _distance_to_price(zone, last_price)
            if _distance_to_price(zone, last_price) is not None
            else float("inf")
        )
    )
    structural_target_context = {
        "contract": "XAU_STRUCTURAL_TARGET_CONTEXT_V229_1",
        "direction": continuation or None,
        "m15_opposing_zones": m15_target_zones[:12],
        "htf_destination_stack": [
            dict(zone) for zone in list(continuation_path.get("destination_stack") or [])
        ],
        "execution_influence": False,
        "execution_authority": False,
    }

    dom_state = str(dom.get("state") or "UNAVAILABLE")
    dom_score = _finite(dom.get("dom_pressure_score"))
    dom_imbalance = _finite(dom.get("last_imbalance"))
    if dom_stale:
        dom_alignment = "DOM_STALE_NO_EFFECT"
    elif first_leg == "LONG" and dom_state == "BID_DOMINANT":
        dom_alignment = "SUPPORTS_FIRST_LEG"
    elif first_leg == "LONG" and dom_state == "ASK_DOMINANT":
        dom_alignment = "OPPOSES_FIRST_LEG"
    elif first_leg == "SHORT" and dom_state == "ASK_DOMINANT":
        dom_alignment = "SUPPORTS_FIRST_LEG"
    elif first_leg == "SHORT" and dom_state == "BID_DOMINANT":
        dom_alignment = "OPPOSES_FIRST_LEG"
    else:
        dom_alignment = "NEUTRAL_OR_CONTESTED"

    micro_direction = str(micro_refinement.get("direction") or "").upper()
    micro_state = str(micro_refinement.get("state") or "")
    micro_confirmed = micro_state == "M5_REFINEMENT_CONFIRMED_SHADOW"
    if (
        not dom_stale
        and path_direction_conflict
        and micro_confirmed
        and micro_direction in {"LONG", "SHORT"}
    ):
        aligned_dom_state = "BID_DOMINANT" if micro_direction == "LONG" else "ASK_DOMINANT"
        opposed_dom_state = "ASK_DOMINANT" if micro_direction == "LONG" else "BID_DOMINANT"
        if dom_state == aligned_dom_state:
            conflict_resolution_evidence = "M5_AND_DOM_ALIGNED_SHADOW"
        elif dom_state == opposed_dom_state:
            conflict_resolution_evidence = "M5_DOM_DISAGREE_WAIT"
        else:
            conflict_resolution_evidence = "M5_CONFIRMED_DOM_NEUTRAL_WAIT"
    elif path_direction_conflict:
        conflict_resolution_evidence = "WAIT_M5_AND_DOM"
    else:
        conflict_resolution_evidence = "NO_PATH_CONFLICT"

    if not event_stale and event_state in {"PRE_EVENT", "EVENT_WINDOW"}:
        if conflict_resolution_evidence == "M5_AND_DOM_ALIGNED_SHADOW":
            conflict_resolution_evidence = (
                "M5_DOM_ALIGNED_BUT_EVENT_RISK_WAIT"
            )
        elif path_direction_conflict:
            conflict_resolution_evidence = (
                f"{conflict_resolution_evidence}_EVENT_RISK_{event_state}"
            )

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
        "structural_target_context": structural_target_context,
        "active_reaction_path": active_path,
        "path_direction_conflict": path_direction_conflict,
        "path_overlap_ratio": path_overlap_ratio,
        "dom_context": {
            "worker": DOM_WORKER,
            "observed_at": (
                None if dom_heartbeat_at is None else dom_heartbeat_at.isoformat()
            ),
            "age_minutes": dom_age_minutes,
            "stale": dom_stale,
            "state": dom_state,
            "pressure_score": dom_score,
            "last_imbalance": dom_imbalance,
            "top5_bid_units": dom.get("top5_bid_units"),
            "top5_ask_units": dom.get("top5_ask_units"),
            "bid_wall": dict(dom.get("bid_wall") or {}),
            "ask_wall": dict(dom.get("ask_wall") or {}),
            "alignment_with_first_leg": dom_alignment,
            "source_scope": "CTRADER_BROKER_VENUE_LEVEL_II_NOT_COMEX",
            "execution_influence": False,
            "execution_authority": False,
        },
        "conflict_resolution_evidence": conflict_resolution_evidence,
        "event_risk_context": {
            "worker": EVENT_RISK_WORKER,
            "observed_at": (
                None if event_heartbeat_at is None else event_heartbeat_at.isoformat()
            ),
            "age_minutes": event_age_minutes,
            "stale": event_stale,
            "state": event_state,
            "action": event_risk.get("action"),
            "minutes_to_focal": event_risk.get("minutes_to_focal"),
            "focal_event": dict(event_risk.get("focal_event") or {}),
            "upcoming_events": list(event_risk.get("upcoming_events") or []),
            "official_or_cadence_verified_count": event_details.get(
                "official_or_cadence_verified_count"
            ),
            "discovery_unverified_count": event_details.get(
                "discovery_unverified_count"
            ),
            "source_status": dict(event_details.get("source_status") or {}),
            "execution_influence": False,
            "execution_authority": False,
        },
        "path_conflict_state": (
            "OVERLAPPING_H1_SUPPLY_DEMAND_COMPRESSION_WAIT_MICRO_RESOLUTION"
            if path_direction_conflict
            else "NO_PATH_DIRECTION_CONFLICT"
        ),
        "micro_resolution_required": path_direction_conflict,
        "micro_refinement": micro_refinement,
        "first_leg_micro_refinement": (
            micro_refinement
            if str(micro_refinement.get("direction") or "").upper() == first_leg
            else {}
        ),
        "m5_path_projection": m5_path_projection,
        "first_leg_m5_path_projection": (
            m5_path_projection
            if str(
                dict(m5_path_projection.get("current_leg") or {}).get("direction")
                or ""
            ).upper() == first_leg
            else {}
        ),
        "prepare_only_fallback": bool(not canonical and not stale),
        "required_for_execution": False,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "Supply/demand is AFIC context and preparation evidence only. "
            "Path mapping can identify the next opposing zone and internal waypoints. "
            "If opposing H1 source zones overlap materially, the state is compression/conflict. "
            "V189 microstructure, V191 broker-venue DOM and V192 event risk may provide "
            "aligned or cautionary shadow evidence, but none can create execution authority."
        ),
    }
    out["supply_demand_context"] = context
    return out


def context_token(payload: dict[str, Any]) -> tuple[str, ...]:
    context = dict(payload.get("supply_demand_context") or {})
    same = dict(context.get("same_direction_zone") or {})
    opposite = dict(context.get("opposite_reversal_zone") or {})
    first_leg_path = dict(context.get("first_leg_path") or {})
    micro = dict(context.get("first_leg_micro_refinement") or {})
    projection = dict(context.get("first_leg_m5_path_projection") or {})
    projection_current = dict(projection.get("current_leg") or {})
    projection_next = dict(projection.get("next_leg") or {})
    primary_target = dict(first_leg_path.get("primary_opposing_zone") or {})
    structural_targets = dict(context.get("structural_target_context") or {})
    m15_target_ids = ",".join(
        str(dict(item).get("zone_id") or "NONE")
        for item in list(structural_targets.get("m15_opposing_zones") or [])[:6]
    )
    htf_target_ids = ",".join(
        str(dict(item).get("zone_id") or "NONE")
        for item in list(structural_targets.get("htf_destination_stack") or [])[:6]
    )
    return (
        str(context.get("state") or "NONE"),
        str(context.get("atlas_observed_at") or "NONE"),
        str(same.get("zone_id") or "NONE"),
        str(opposite.get("zone_id") or "NONE"),
        str(context.get("same_direction_confluence") or False),
        str(context.get("opposite_zone_near_price") or False),
        str(first_leg_path.get("state") or "NONE"),
        str(primary_target.get("zone_id") or "NONE"),
        m15_target_ids or "NONE",
        htf_target_ids or "NONE",
        str(micro.get("state") or "NONE"),
        str(dict(micro.get("refined_entry_pocket") or {}).get("origin_at") or "NONE"),
        str(projection.get("state") or "NONE"),
        str(projection_current.get("pocket_state") or "NONE"),
        str(projection_next.get("pocket_state") or "NONE"),
        str(context.get("path_direction_conflict") or False),
    )

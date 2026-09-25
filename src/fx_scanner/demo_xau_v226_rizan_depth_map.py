from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
import os
from typing import Any, Sequence

import pandas as pd

from .execution.policy import load_execution_policy
from .research_xau_zone_path_v174 import wilson_lower_bound
from .research_xau_zone_reversal_depth_v225 import (
    _detect_m15_zones,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_v226_rizan_depth_map"
CONTRACT = "XAU_RIZAN_DEPTH_MAP_V226"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
HISTORY_WORKER = "research_xau_zone_reversal_depth_v225"
POLICY_EFFECT = "SHADOW_ONLY"
MIN_HAZARD_AT_RISK = 30
REQUIRED_HISTORY_VERSION = "XAU_ZONE_REVERSAL_DEPTH_V225_2"


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


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


def _direction(value: Any) -> str:
    side = str(value or "").upper()
    return side if side in {"LONG", "SHORT"} else ""


def _active(zone: dict[str, Any]) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    if lifecycle and lifecycle.get("active") is False:
        return False
    status = str(zone.get("status") or "").upper()
    return "BROKEN" not in status and "INVALID" not in status


def _zone_width(zone: dict[str, Any]) -> float:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return 0.0
    return max(0.0, high - low)


def _distance_to_zone(price: float, zone: dict[str, Any]) -> float:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return float("inf")
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _overlap_bounds(
    a_low: float,
    a_high: float,
    b_low: float,
    b_high: float,
) -> tuple[float, float] | None:
    low = max(float(a_low), float(b_low))
    high = min(float(a_high), float(b_high))
    return None if high < low else (low, high)


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_low = _f(a.get("low"))
    a_high = _f(a.get("high"))
    b_low = _f(b.get("low"))
    b_high = _f(b.get("high"))
    if None in {a_low, a_high, b_low, b_high}:
        return 0.0
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    denom = max(min(a_high - a_low, b_high - b_low), 1e-12)
    return overlap / denom


def _collect_atlas_zones(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def add(raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        zone = dict(raw)
        if _direction(zone.get("direction")) not in {"LONG", "SHORT"}:
            return
        if _f(zone.get("low")) is None or _f(zone.get("high")) is None:
            return
        candidates.append(zone)

    for item in list(evaluation.get("zones") or []):
        add(item)

    path_map = dict(evaluation.get("path_map") or {})
    for key in ("nearest_demand", "nearest_supply"):
        add(path_map.get(key))
    for key in ("demand_source_stack", "supply_source_stack"):
        for item in list(path_map.get(key) or []):
            add(item)

    projection = dict(evaluation.get("m5_path_projection") or {})
    for leg_key in ("current_leg", "next_leg"):
        leg = dict(projection.get(leg_key) or {})
        add(leg.get("source_zone"))
        add(leg.get("terminal_target_zone"))

    dedup: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for zone in candidates:
        key = str(zone.get("zone_id") or "")
        if not key:
            anonymous.append(zone)
            continue
        previous = dedup.get(key)
        if previous is None or len(zone) > len(previous):
            dedup[key] = zone
    output = list(dedup.values()) + anonymous
    return [zone for zone in output if _active(zone)]


def _full_zone_price(zone: dict[str, Any], depth: float) -> float | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = _direction(zone.get("direction"))
    if low is None or high is None or high <= low or not direction:
        return None
    d = float(depth)
    if direction == "LONG":
        return high - d * (high - low)
    return low + d * (high - low)


def _depth_band_prices(
    zone: dict[str, Any],
    lower_depth: float,
    upper_depth: float,
) -> dict[str, Any]:
    first = _full_zone_price(zone, lower_depth)
    second = _full_zone_price(zone, upper_depth)
    if first is None or second is None:
        return {}
    return {
        "low": min(first, second),
        "high": max(first, second),
        "lower_depth": float(lower_depth),
        "upper_depth": float(upper_depth),
    }


def _profile_key_findings(
    history_details: dict[str, Any],
    timeframe: str,
    direction: str,
) -> dict[str, Any]:
    for item in list(history_details.get("key_findings") or []):
        row = dict(item)
        if (
            str(row.get("timeframe") or "").upper() == timeframe
            and str(row.get("direction") or "").upper() == direction
        ):
            return row
    return {}


def _hazard_bands(
    history_details: dict[str, Any],
    timeframe: str,
    direction: str,
) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    eras = dict(history_details.get("eras") or {})
    for era_name, raw_era in eras.items():
        era = dict(raw_era or {})
        summary = dict(era.get("summary") or {})
        tf = dict(summary.get(timeframe) or {})
        side = dict(tf.get(direction) or {})
        for raw_band in list(side.get("hazard_by_depth_band") or []):
            band = dict(raw_band)
            name = str(band.get("band") or "")
            if not name:
                continue
            bucket = aggregated.setdefault(
                name,
                {
                    "band": name,
                    "lower_depth": _f(band.get("lower_depth")),
                    "upper_depth": _f(band.get("upper_depth")),
                    "at_risk": 0,
                    "reversals": 0,
                    "eras": [],
                },
            )
            bucket["at_risk"] += int(band.get("at_risk") or 0)
            bucket["reversals"] += int(band.get("reversals") or 0)
            bucket["eras"].append(
                {
                    "era": str(era_name),
                    "hazard": _f(band.get("hazard")),
                    "at_risk": int(band.get("at_risk") or 0),
                }
            )

    rows: list[dict[str, Any]] = []
    for item in aggregated.values():
        at_risk = int(item["at_risk"])
        reversals = int(item["reversals"])
        rows.append(
            {
                **item,
                "hazard": None if at_risk <= 0 else reversals / at_risk,
                "wilson_lower_95": (
                    None if at_risk <= 0
                    else wilson_lower_bound(reversals, at_risk)
                ),
            }
        )
    rows.sort(key=lambda row: float(row.get("lower_depth") or 0.0))
    return rows


def _historical_profile(
    history_details: dict[str, Any],
    timeframe: str,
    direction: str,
) -> dict[str, Any]:
    finding = _profile_key_findings(history_details, timeframe, direction)
    bands = _hazard_bands(history_details, timeframe, direction)
    touches = int(finding.get("touches") or 0)

    running = 0
    enriched: list[dict[str, Any]] = []
    for row in bands:
        running += int(row.get("reversals") or 0)
        enriched.append(
            {
                **row,
                "cumulative_reversal_share_of_all_touches": (
                    None if touches <= 0 else running / touches
                ),
            }
        )

    eligible = [
        row for row in enriched
        if int(row.get("at_risk") or 0) >= MIN_HAZARD_AT_RISK
    ]
    top = (
        max(
            eligible,
            key=lambda row: (
                float(row.get("hazard") or 0.0),
                float(row.get("wilson_lower_95") or 0.0),
                int(row.get("at_risk") or 0),
            ),
        )
        if eligible else {}
    )

    era_top_bands: list[dict[str, Any]] = []
    eras = dict(history_details.get("eras") or {})
    for era_name, raw_era in eras.items():
        summary = dict(dict(raw_era or {}).get("summary") or {})
        side = dict(dict(summary.get(timeframe) or {}).get(direction) or {})
        top_rows = list(side.get("highest_hazard_bands_min_n") or [])
        era_top_bands.append(
            {
                "era": str(era_name),
                "band": None if not top_rows else dict(top_rows[0]).get("band"),
                "touches": int(side.get("touches") or 0),
                "hold_rate": _f(side.get("hold_rate")),
                "median_depth": _f(side.get("depth_median")),
            }
        )
    distinct_top = {
        str(row.get("band"))
        for row in era_top_bands
        if row.get("band")
    }

    return {
        "timeframe": timeframe,
        "direction": direction,
        "touches": touches,
        "hold_rate": _f(finding.get("hold_rate")),
        "hold_wilson_lower_95": _f(finding.get("hold_wilson_lower_95")),
        "depth_p25": _f(finding.get("depth_p25")),
        "depth_median": _f(finding.get("depth_median")),
        "depth_p75": _f(finding.get("depth_p75")),
        "highest_hazard_band": top,
        "hazard_bands": enriched,
        "era_top_bands": era_top_bands,
        "stable_top_band_across_eras": len(distinct_top) == 1 and len(era_top_bands) >= 3,
        "coordinate": "FULL_ZONE_NEAR_EDGE_TO_FAR_EDGE",
        "source_contract": history_details.get("contract"),
        "source_research_version": history_details.get("research_version"),
    }


def _historical_hierarchy(history_details: dict[str, Any]) -> dict[str, Any]:
    hierarchy = dict(history_details.get("hierarchy") or {})
    return {
        "h4_successes": int(hierarchy.get("h4_successes") or 0),
        "h1_child_coverage": _f(hierarchy.get("h1_child_coverage")),
        "m15_child_coverage_given_h1": _f(
            hierarchy.get("m15_child_coverage_given_h1")
        ),
        "h1_child_depth": dict(hierarchy.get("h1_child_depth") or {}),
        "m15_child_depth": dict(hierarchy.get("m15_child_depth") or {}),
    }


def _applicability(zone: dict[str, Any], price: float) -> dict[str, Any]:
    lifecycle = dict(zone.get("lifecycle") or {})
    touches = int(lifecycle.get("touch_count") or 0)
    freshness = str(lifecycle.get("freshness") or "UNKNOWN").upper()
    inside = _distance_to_zone(price, zone) <= 1e-9

    if touches == 0 and freshness == "FRESH":
        state = "HIGH_FIRST_TOUCH_PRIOR"
        note = "Belum tersentuh; paling dekat dengan populasi first-touch V225.2."
    elif touches <= 1 and inside:
        state = "MEDIUM_FIRST_TOUCH_IN_PROGRESS"
        note = "First touch sedang/baru berlangsung; prior historis masih kontekstual."
    elif touches <= 1:
        state = "MEDIUM_POST_FIRST_TOUCH_CONTEXT"
        note = "First touch sudah terjadi; jangan menganggap band sebagai forecast touch baru."
    else:
        state = "LOW_REUSE_OUT_OF_SAMPLE"
        note = "Multi-tested/reused; V225.2 tidak mengkalibrasi reuse sebagai first touch baru."

    return {
        "state": state,
        "touch_count": touches,
        "freshness": freshness,
        "inside_now": inside,
        "note": note,
    }


def _standalone_layer(
    zone: dict[str, Any],
    profile: dict[str, Any],
    *,
    price: float,
) -> dict[str, Any]:
    top = dict(profile.get("highest_hazard_band") or {})
    lower = _f(top.get("lower_depth"))
    upper = _f(top.get("upper_depth"))
    hotspot = (
        {}
        if lower is None or upper is None
        else _depth_band_prices(zone, lower, upper)
    )

    quantiles = {}
    for name, key in (
        ("p25", "depth_p25"),
        ("median", "depth_median"),
        ("p75", "depth_p75"),
    ):
        depth = _f(profile.get(key))
        quantiles[name] = {
            "depth": depth,
            "price": None if depth is None else _full_zone_price(zone, depth),
        }

    return {
        "zone": zone,
        "historical_profile": profile,
        "hotspot": hotspot,
        "quantiles": quantiles,
        "applicability": _applicability(zone, price),
    }


def _candidate_sort_key(zone: dict[str, Any], price: float) -> tuple[Any, ...]:
    lifecycle = dict(zone.get("lifecycle") or {})
    touches = int(lifecycle.get("touch_count") or 0)
    reuse_penalty = 0 if touches == 0 else 1 if touches == 1 else 2
    return (
        _distance_to_zone(price, zone),
        reuse_penalty,
        -float(_f(zone.get("research_score")) or 0.0),
        _zone_width(zone),
    )


def _clean_first_touch_candidate(
    zone: dict[str, Any],
    *,
    direction: str,
    price: float,
) -> bool:
    lifecycle = dict(zone.get("lifecycle") or {})
    if int(lifecycle.get("touch_count") or 0) != 0:
        return False
    if str(lifecycle.get("freshness") or "").upper() != "FRESH":
        return False
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None:
        return False
    if direction == "LONG":
        return price > high
    if direction == "SHORT":
        return price < low
    return False


def _select_nearest_h4_context(
    zones: Sequence[dict[str, Any]],
    *,
    direction: str,
    price: float,
) -> dict[str, Any]:
    candidates = [
        dict(zone)
        for zone in zones
        if str(zone.get("timeframe") or "").upper() == "H4"
        and _direction(zone.get("direction")) == direction
        and _active(zone)
    ]
    if not candidates:
        return {}
    candidates.sort(key=lambda zone: _candidate_sort_key(zone, price))
    return candidates[0]


def _select_h4(
    zones: Sequence[dict[str, Any]],
    *,
    direction: str,
    price: float,
) -> dict[str, Any]:
    candidates = [
        dict(zone)
        for zone in zones
        if str(zone.get("timeframe") or "").upper() == "H4"
        and _direction(zone.get("direction")) == direction
        and _active(zone)
    ]
    if not candidates:
        return {}

    # V225.2 is a first-touch study. Prefer an untouched fresh H4 parent that
    # still lies ahead of price on the correct approach side. This keeps the
    # calibrated parent aligned with the population used to estimate depth.
    fresh = [
        zone for zone in candidates
        if _clean_first_touch_candidate(
            zone,
            direction=direction,
            price=price,
        )
    ]
    if fresh:
        fresh.sort(
            key=lambda zone: (
                _distance_to_zone(price, zone),
                -float(_f(zone.get("research_score")) or 0.0),
                _zone_width(zone),
            )
        )
        return fresh[0]

    # If no clean first-touch H4 exists, retain the nearest active H4 only as
    # contextual research. Applicability will mark reused zones as low.
    candidates.sort(key=lambda zone: _candidate_sort_key(zone, price))
    return candidates[0]


def _select_h1(
    zones: Sequence[dict[str, Any]],
    *,
    parent: dict[str, Any],
    hotspot: dict[str, Any],
    direction: str,
    price: float,
) -> dict[str, Any]:
    if not parent:
        return {}
    p_low = _f(parent.get("low"))
    p_high = _f(parent.get("high"))
    if p_low is None or p_high is None:
        return {}

    candidates = [
        dict(zone)
        for zone in zones
        if str(zone.get("timeframe") or "").upper() == "H1"
        and _direction(zone.get("direction")) == direction
        and _active(zone)
        and _overlap_bounds(
            p_low,
            p_high,
            float(_f(zone.get("low")) or 0.0),
            float(_f(zone.get("high")) or 0.0),
        ) is not None
    ]
    if not candidates:
        return {}

    h_low = _f(hotspot.get("low"))
    h_high = _f(hotspot.get("high"))

    def key(zone: dict[str, Any]) -> tuple[Any, ...]:
        z_low = float(_f(zone.get("low")) or 0.0)
        z_high = float(_f(zone.get("high")) or 0.0)
        hotspot_overlap = (
            0.0
            if h_low is None or h_high is None
            else max(0.0, min(z_high, h_high) - max(z_low, h_low))
        )
        return (
            -int(hotspot_overlap > 0),
            -hotspot_overlap,
            _distance_to_zone(price, zone),
            -float(_f(zone.get("research_score")) or 0.0),
            _zone_width(zone),
        )

    candidates.sort(key=key)
    return candidates[0]


def _m15_frame(raw_bars: Sequence[dict[str, Any]]) -> pd.DataFrame:
    if not raw_bars:
        return pd.DataFrame()
    frame = pd.DataFrame(list(raw_bars))
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=list(required))
        .sort_values("time")
        .drop_duplicates("time", keep="last")
        .reset_index(drop=True)
    )


def _m15_lifecycle(
    zone: Any,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    available = pd.Timestamp(zone.available_at)
    sample = frame[frame["time"] >= available]
    touches = 0
    was_inside = False
    invalidated_at = None
    for _, row in sample.iterrows():
        inside = float(row["low"]) <= float(zone.high) and float(row["high"]) >= float(zone.low)
        if inside and not was_inside:
            touches += 1
        invalid = (
            float(row["close"]) < float(zone.distal)
            if zone.direction == "LONG"
            else float(row["close"]) > float(zone.distal)
        )
        if invalid:
            invalidated_at = pd.Timestamp(row["time"]).to_pydatetime().isoformat()
            break
        was_inside = inside
    return {
        "active": invalidated_at is None,
        "touch_count": touches,
        "freshness": (
            "BROKEN" if invalidated_at is not None
            else "FRESH" if touches == 0
            else "FIRST_TEST" if touches == 1
            else "MULTI_TESTED"
        ),
        "invalidated_at": invalidated_at,
    }


def _runtime_m15_zones(raw_bars: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = _m15_frame(raw_bars)
    if frame.empty or len(frame) < 20:
        return []
    zones = _detect_m15_zones(frame)
    output: list[dict[str, Any]] = []
    for zone in zones:
        lifecycle = _m15_lifecycle(zone, frame)
        if not bool(lifecycle.get("active")):
            continue
        output.append(
            {
                "zone_id": zone.zone_id,
                "timeframe": "M15",
                "zone_class": zone.zone_class,
                "pattern": zone.pattern,
                "direction": zone.direction,
                "low": float(zone.low),
                "high": float(zone.high),
                "proximal": float(zone.proximal),
                "distal": float(zone.distal),
                "available_at": zone.available_at.isoformat(),
                "origin_at": zone.origin_at.isoformat(),
                "departure_at": zone.departure_at.isoformat(),
                "atr_points": float(zone.atr_points),
                "base_range_atr": float(zone.base_range_atr),
                "departure_range_atr": float(zone.departure_range_atr),
                "departure_body_fraction": float(zone.departure_body_fraction),
                "lifecycle": lifecycle,
                "status": "RIZAN_DEPTH_M15_SHADOW",
                "execution_influence": False,
                "execution_authority": False,
            }
        )
    output.sort(
        key=lambda zone: _dt(zone.get("available_at"))
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return output


def _select_m15(
    zones: Sequence[dict[str, Any]],
    *,
    parent: dict[str, Any],
    locator: dict[str, Any],
    direction: str,
    price: float,
) -> dict[str, Any]:
    if not parent:
        return {}
    p_low = _f(parent.get("low"))
    p_high = _f(parent.get("high"))
    if p_low is None or p_high is None:
        return {}

    candidates = [
        dict(zone)
        for zone in zones
        if _direction(zone.get("direction")) == direction
        and _active(zone)
        and _overlap_bounds(
            p_low,
            p_high,
            float(_f(zone.get("low")) or 0.0),
            float(_f(zone.get("high")) or 0.0),
        ) is not None
    ]
    if not candidates:
        return {}

    l_low = _f(locator.get("low"))
    l_high = _f(locator.get("high"))

    def key(zone: dict[str, Any]) -> tuple[Any, ...]:
        z_low = float(_f(zone.get("low")) or 0.0)
        z_high = float(_f(zone.get("high")) or 0.0)
        locator_overlap = (
            0.0
            if l_low is None or l_high is None
            else max(0.0, min(z_high, l_high) - max(z_low, l_low))
        )
        observed = _dt(zone.get("available_at"))
        return (
            -int(locator_overlap > 0),
            -locator_overlap,
            _distance_to_zone(price, zone),
            _zone_width(zone),
            -(observed.timestamp() if observed is not None else 0.0),
        )

    candidates.sort(key=key)
    return candidates[0]


def _nested_locator(
    zone: dict[str, Any],
    nested_profile: dict[str, Any],
) -> dict[str, Any]:
    if not zone or not nested_profile:
        return {}
    p25 = _f(nested_profile.get("p25"))
    median = _f(nested_profile.get("median"))
    p75 = _f(nested_profile.get("p75"))
    if p25 is None or median is None or p75 is None:
        return {}
    envelope = _depth_band_prices(zone, p25, p75)
    return {
        "envelope": envelope,
        "median": {
            "depth": median,
            "price": _full_zone_price(zone, median),
        },
        "profile": {
            "n_total": int(nested_profile.get("n_total") or 0),
            "n_inside_0_100": int(nested_profile.get("n_inside_0_100") or 0),
            "p25": p25,
            "median": median,
            "p75": p75,
            "modal_bands": list(nested_profile.get("modal_bands") or []),
        },
    }


def _clip_nested_locator(
    locator: dict[str, Any],
    parent_geometry: dict[str, Any],
) -> dict[str, Any]:
    if not locator or not parent_geometry:
        return dict(locator or {})
    envelope = dict(locator.get("envelope") or {})
    e_low = _f(envelope.get("low"))
    e_high = _f(envelope.get("high"))
    p_low = _f(parent_geometry.get("low"))
    p_high = _f(parent_geometry.get("high"))
    if None in {e_low, e_high, p_low, p_high}:
        return dict(locator)

    overlap = _overlap_bounds(
        float(e_low),
        float(e_high),
        float(p_low),
        float(p_high),
    )
    if overlap is None:
        return {}

    clipped_low, clipped_high = overlap
    clipped = dict(locator)
    clipped["raw_envelope"] = envelope
    clipped["envelope"] = {
        **envelope,
        "low": clipped_low,
        "high": clipped_high,
        "clipped_to_parent": (
            abs(clipped_low - float(e_low)) > 1e-12
            or abs(clipped_high - float(e_high)) > 1e-12
        ),
    }
    clipped["clip_parent"] = {
        "low": float(p_low),
        "high": float(p_high),
    }
    return clipped


def _overlay(
    *,
    timeframe: str,
    direction: str,
    kind: str,
    geometry: dict[str, Any],
    label: str,
    median_price: float | None = None,
    visible_on: Sequence[str],
    applicability: str | None = None,
) -> dict[str, Any]:
    low = _f(geometry.get("low"))
    high = _f(geometry.get("high"))
    if low is None or high is None:
        return {}
    return {
        "timeframe": timeframe,
        "direction": direction,
        "kind": kind,
        "low": low,
        "high": high,
        "label": label,
        "median_price": median_price,
        "visible_on": list(visible_on),
        "applicability": applicability,
    }



def _depth_entry_candidate(
    *,
    direction: str,
    price: float,
    h4: dict[str, Any],
    h1_nested: dict[str, Any],
    m15_nested: dict[str, Any],
    h1_profile: dict[str, Any],
    m15_profile: dict[str, Any],
    h4_selection_mode: str,
) -> dict[str, Any]:
    """Build one display-only entry candidate from the narrowest causal locator.

    This is deliberately not an execution signal. M15 nested geometry wins when
    available, otherwise H1 nested geometry, otherwise the H4 historical hotspot.
    """
    m15_geometry = dict(m15_nested.get("envelope") or {})
    h1_geometry = dict(h1_nested.get("envelope") or {})
    h4_geometry = dict(h4.get("hotspot") or {})

    source_layer = ""
    geometry: dict[str, Any] = {}
    reference = None
    if m15_geometry:
        source_layer = "M15_NESTED_LOCATOR"
        geometry = m15_geometry
        reference = _f(dict(m15_nested.get("median") or {}).get("price"))
    elif h1_geometry:
        source_layer = "H1_NESTED_LOCATOR"
        geometry = h1_geometry
        reference = _f(dict(h1_nested.get("median") or {}).get("price"))
    elif h4_geometry:
        source_layer = "H4_HISTORICAL_HOTSPOT"
        geometry = h4_geometry

    low = _f(geometry.get("low"))
    high = _f(geometry.get("high"))
    if low is None or high is None or high < low:
        return {}

    if reference is None:
        reference = (low + high) / 2.0
    reference = min(max(float(reference), low), high)

    if low <= price <= high:
        approach_state = "INSIDE_CANDIDATE"
    elif direction == "LONG":
        approach_state = "AHEAD" if price > high else "PASSED_BEYOND_CANDIDATE"
    else:
        approach_state = "AHEAD" if price < low else "PASSED_BEYOND_CANDIDATE"

    h4_profile = dict(h4.get("historical_profile") or {})
    h4_app = dict(h4.get("applicability") or {})
    calibrated_fresh = (
        h4_selection_mode == "FRESH_FIRST_TOUCH_CALIBRATED_PARENT"
        and str(h4_app.get("state") or "") == "HIGH_FIRST_TOUCH_PRIOR"
    )
    display_status = (
        "PREPARE_ONLY_FRESH_FIRST_TOUCH"
        if calibrated_fresh
        else "CONTEXT_ONLY_OUT_OF_SAMPLE"
    )

    return {
        "candidate_type": "DEPTH_ENTRY_CANDIDATE",
        "direction": direction,
        "entry_low": low,
        "entry_high": high,
        "entry_reference": reference,
        "source_layer": source_layer,
        "approach_state": approach_state,
        "distance_points": _distance_to_zone(
            price,
            {"low": low, "high": high},
        ),
        "display_status": display_status,
        "calibrated_fresh_first_touch": calibrated_fresh,
        "historical_context": {
            "reaction_contract": "REACTION_GTE_0_50_ATR",
            "h4_parent_rate": _f(h4_profile.get("hold_rate")),
            "h4_parent_wilson_lower_95": _f(h4_profile.get("hold_wilson_lower_95")),
            "h1_standalone_rate": _f(h1_profile.get("hold_rate")),
            "h1_standalone_wilson_lower_95": _f(
                h1_profile.get("hold_wilson_lower_95")
            ),
            "m15_standalone_rate": _f(m15_profile.get("hold_rate")),
            "m15_standalone_wilson_lower_95": _f(
                m15_profile.get("hold_wilson_lower_95")
            ),
            "note": (
                "Rates are standalone historical reaction/hold rates, not a combined "
                "H4→H1→M15 entry-strategy win rate. The final candidate is being "
                "validated prospectively by V227."
            ),
        },
        "policy_effect": POLICY_EFFECT,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _direction_map(
    *,
    direction: str,
    price: float,
    atlas_zones: Sequence[dict[str, Any]],
    m15_zones: Sequence[dict[str, Any]],
    history_details: dict[str, Any],
    hierarchy: dict[str, Any],
) -> dict[str, Any]:
    h4_profile = _historical_profile(history_details, "H4", direction)
    h1_profile = _historical_profile(history_details, "H1", direction)
    m15_profile = _historical_profile(history_details, "M15", direction)

    nearest_h4_context_zone = _select_nearest_h4_context(
        atlas_zones,
        direction=direction,
        price=price,
    )
    h4_zone = _select_h4(atlas_zones, direction=direction, price=price)
    if not h4_zone:
        return {
            "direction": direction,
            "state": "NO_ACTIVE_H4_PARENT",
            "h4_profile": h4_profile,
            "h1_profile": h1_profile,
            "m15_standalone_profile": m15_profile,
            "execution_influence": False,
            "execution_authority": False,
        }

    h4 = _standalone_layer(h4_zone, h4_profile, price=price)
    nearest_h4_context = (
        {}
        if not nearest_h4_context_zone
        else {
            "zone": nearest_h4_context_zone,
            "applicability": _applicability(nearest_h4_context_zone, price),
            "same_as_calibrated_parent": (
                str(nearest_h4_context_zone.get("zone_id") or "")
                == str(h4_zone.get("zone_id") or "")
            ),
        }
    )
    h4_selection_mode = (
        "FRESH_FIRST_TOUCH_CALIBRATED_PARENT"
        if _clean_first_touch_candidate(
            h4_zone,
            direction=direction,
            price=price,
        )
        else "FALLBACK_CONTEXT_ONLY"
    )

    h1_zone = _select_h1(
        atlas_zones,
        parent=h4_zone,
        hotspot=dict(h4.get("hotspot") or {}),
        direction=direction,
        price=price,
    )
    h1 = (
        {}
        if not h1_zone
        else _standalone_layer(h1_zone, h1_profile, price=price)
    )

    h1_nested_raw = _nested_locator(
        h1_zone,
        dict(hierarchy.get("h1_child_depth") or {}),
    )
    h1_nested = _clip_nested_locator(
        h1_nested_raw,
        h4_zone,
    )
    m15_parent = h1_zone or h4_zone
    m15_locator_parent = (
        dict(h1_nested.get("envelope") or {})
        or dict(h4.get("hotspot") or {})
    )
    m15_zone = _select_m15(
        m15_zones,
        parent=m15_parent,
        locator=m15_locator_parent,
        direction=direction,
        price=price,
    )
    m15_nested_raw = _nested_locator(
        m15_zone,
        dict(hierarchy.get("m15_child_depth") or {}),
    )
    m15_nested = _clip_nested_locator(
        m15_nested_raw,
        m15_locator_parent,
    )

    overlays: list[dict[str, Any]] = []
    h4_hotspot = _overlay(
        timeframe="H4",
        direction=direction,
        kind="H4_HISTORICAL_HOTSPOT",
        geometry=dict(h4.get("hotspot") or {}),
        label="H4 depth hotspot",
        median_price=_f(dict(h4.get("quantiles") or {}).get("median", {}).get("price")),
        visible_on=("H4", "H1", "M15"),
        applicability=str(dict(h4.get("applicability") or {}).get("state") or ""),
    )
    if h4_hotspot:
        overlays.append(h4_hotspot)

    if h1_zone:
        h1_geometry = (
            dict(h1_nested.get("envelope") or {})
            or dict(h1.get("hotspot") or {})
        )
        h1_overlay = _overlay(
            timeframe="H1",
            direction=direction,
            kind="H1_NESTED_LOCATOR",
            geometry=h1_geometry,
            label="H1 nested locator",
            median_price=_f(dict(h1_nested.get("median") or {}).get("price")),
            visible_on=("H1", "M15"),
            applicability=str(dict(h1.get("applicability") or {}).get("state") or ""),
        )
        if h1_overlay:
            overlays.append(h1_overlay)

    if m15_zone and m15_nested:
        m15_overlay = _overlay(
            timeframe="M15",
            direction=direction,
            kind="M15_NESTED_LOCATOR",
            geometry=dict(m15_nested.get("envelope") or {}),
            label="M15 nested locator",
            median_price=_f(dict(m15_nested.get("median") or {}).get("price")),
            visible_on=("M15",),
            applicability=str(_applicability(m15_zone, price).get("state") or ""),
        )
        if m15_overlay:
            overlays.append(m15_overlay)

    narrowest = (
        dict(m15_nested.get("envelope") or {})
        or dict(h1_nested.get("envelope") or {})
        or dict(h4.get("hotspot") or {})
    )
    state = (
        "H4_H1_M15_LOCATOR_AVAILABLE"
        if m15_zone and m15_nested
        else "H4_H1_LOCATOR_AVAILABLE"
        if h1_zone
        else "H4_DEPTH_HOTSPOT_AVAILABLE"
    )
    depth_entry_candidate = _depth_entry_candidate(
        direction=direction,
        price=price,
        h4=h4,
        h1_nested=h1_nested,
        m15_nested=m15_nested,
        h1_profile=h1_profile,
        m15_profile=m15_profile,
        h4_selection_mode=h4_selection_mode,
    )

    return {
        "direction": direction,
        "state": state,
        "price_reference": price,
        "h4": h4,
        "h4_selection_mode": h4_selection_mode,
        "nearest_h4_context": nearest_h4_context,
        "h1": {
            **h1,
            "nested_locator": h1_nested,
        } if h1 else {},
        "m15": {
            "zone": m15_zone,
            "nested_locator": m15_nested,
            "standalone_profile_context": m15_profile,
            "applicability": _applicability(m15_zone, price) if m15_zone else {},
            "note": (
                "Standalone M15 uses the causal-close V225.2 first-touch depth profile. "
                "When M15 is nested under a successful H4/H1 path, V226 keeps that "
                "standalone prior separate and uses the historical nested-child locator "
                "distribution for hierarchical narrowing."
            ),
        } if m15_zone else {
            "standalone_profile_context": m15_profile,
        },
        "historical_hierarchy": hierarchy,
        "narrowest_locator": narrowest,
        "depth_entry_candidate": depth_entry_candidate,
        "overlays": overlays,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def build_depth_map(
    *,
    atlas_evaluation: dict[str, Any],
    history_details: dict[str, Any],
) -> dict[str, Any]:
    price = _f(atlas_evaluation.get("last_closed_m15_price"))
    if price is None:
        return {
            "contract": CONTRACT,
            "state": "NO_PRICE_REFERENCE",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    history_version = str(history_details.get("research_version") or "")
    if history_version != REQUIRED_HISTORY_VERSION:
        return {
            "contract": CONTRACT,
            "state": "HISTORICAL_PRIOR_VERSION_MISMATCH",
            "price_reference": price,
            "required_history_version": REQUIRED_HISTORY_VERSION,
            "observed_history_version": history_version or None,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    if int(history_details.get("year_count") or 0) < 15:
        return {
            "contract": CONTRACT,
            "state": "HISTORICAL_PRIOR_INCOMPLETE",
            "price_reference": price,
            "required_history_version": REQUIRED_HISTORY_VERSION,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    atlas_zones = _collect_atlas_zones(atlas_evaluation)
    m15_zones = _runtime_m15_zones(
        list(atlas_evaluation.get("chart_bars_m15") or [])
    )
    hierarchy = _historical_hierarchy(history_details)

    long_map = _direction_map(
        direction="LONG",
        price=price,
        atlas_zones=atlas_zones,
        m15_zones=m15_zones,
        history_details=history_details,
        hierarchy=hierarchy,
    )
    short_map = _direction_map(
        direction="SHORT",
        price=price,
        atlas_zones=atlas_zones,
        m15_zones=m15_zones,
        history_details=history_details,
        hierarchy=hierarchy,
    )

    projection = dict(atlas_evaluation.get("m5_path_projection") or {})
    focus = _direction(dict(projection.get("current_leg") or {}).get("direction"))
    if not focus:
        focus = min(
            ("LONG", "SHORT"),
            key=lambda side: (
                _distance_to_zone(
                    price,
                    dict(dict(long_map if side == "LONG" else short_map).get("h4") or {}).get("zone")
                    or {},
                )
            ),
        )

    overlays = list(long_map.get("overlays") or []) + list(short_map.get("overlays") or [])
    focus_map = long_map if focus == "LONG" else short_map
    focus_entry_candidate = dict(focus_map.get("depth_entry_candidate") or {})
    return {
        "contract": CONTRACT,
        "state": "RIZAN_DEPTH_MAP_AVAILABLE",
        "as_of": atlas_evaluation.get("as_of"),
        "price_reference": price,
        "focus_direction": focus,
        "depth_entry_candidate": focus_entry_candidate,
        "entry_candidates": {
            "long": dict(long_map.get("depth_entry_candidate") or {}),
            "short": dict(short_map.get("depth_entry_candidate") or {}),
        },
        "long": long_map,
        "short": short_map,
        "chart_overlays": overlays,
        "historical_prior": {
            "years": list(history_details.get("years") or []),
            "year_count": int(history_details.get("year_count") or 0),
            "episode_count": int(history_details.get("episode_count") or 0),
            "research_version": history_details.get("research_version"),
            "required_research_version": REQUIRED_HISTORY_VERSION,
            "coordinate": "FULL_ZONE_NEAR_EDGE_TO_FAR_EDGE",
        },
        "interpretation": (
            "V226 localizes current active H4 supply/demand using V225.2 first-touch "
            "depth priors. A fresh untouched H4 on the correct approach side is preferred "
            "as the calibrated parent; the nearest reused H4 is retained separately as "
            "market context. The calibrated parent is then narrowed with an overlapping "
            "H1 child and a pre-existing same-direction M15 child when available. "
            "Nested child envelopes are clipped to their parent locator so each stage truly "
            "narrows rather than expanding outside the upstream geometry. The narrowest "
            "available geometry is exposed as a display-only Depth Entry Candidate with "
            "direction, price range and reference price. No MSS/reclaim is required to draw "
            "the map, and the map/candidate have no execution authority."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V226_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V226_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    evaluation: dict[str, Any] = {}

    try:
        atlas_hb = _latest_heartbeat(store, ATLAS_WORKER)
        history_hb = _latest_heartbeat(store, HISTORY_WORKER)
        atlas_details = dict(atlas_hb.get("details") or {})
        history_details = dict(history_hb.get("details") or {})
        if not bool(atlas_hb.get("healthy")):
            raise RuntimeError("V226_ATLAS_UNHEALTHY")
        if not bool(history_hb.get("healthy")):
            raise RuntimeError("V226_HISTORY_UNHEALTHY")
        evaluation = build_depth_map(
            atlas_evaluation=dict(atlas_details.get("evaluation") or {}),
            history_details=history_details,
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
            "policy_effect": POLICY_EFFECT,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": now.isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V226_RIZAN_DEPTH_MAP "
        f"healthy={healthy} state={evaluation.get('state','ERROR')} "
        f"focus={evaluation.get('focus_direction','—')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

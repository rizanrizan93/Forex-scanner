from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_afic_path_shadow_observer import _atr
from .demo_xau_supply_demand_atlas_v182 import (
    SDZone,
    _classify_pattern,
    _stable_sd_zone_id,
)
from .models import ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    DepthEpisode,
    _base_geometry,
    _load_price_frame,
    _overlaps,
    _resample_ohlc,
    _quantile,
    build_depth_dataset,
    normalized_depth,
    normalized_internal_depth,
)

RESEARCH_VERSION = "XAU_NESTED_M5_DEPTH_V228_1"
ARTIFACT_CONTRACT = "XAU_NESTED_M5_DEPTH_V228_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

M5_MIN_DEPARTURE_RANGE_ATR = 1.00
M5_MIN_DEPARTURE_BODY_FRACTION = 0.50
M5_MAX_BASE_RANGE_ATR = 1.25
M5_ACTIVE_HOURS = 24.0
M5_SUPERSESSION_GAP_MINUTES = 5.1
M5_OVERLAP_REPLACE = 0.70
LADDER_QUANTILES = (0.10, 0.35, 0.60, 0.85)

# Frozen from the finalized causal-close V225.2 2012–2026 evidence.
# These are used only as a pre-registered historical prior for ranking M5
# children; they do not grant execution authority and are not re-fit per year.
V2252_M15_DEPTH_PRIOR = {
    "LONG": {
        "p25": 0.07594936708854201,
        "median": 0.20634920634920062,
        "p75": 0.44541634835752575,
    },
    "SHORT": {
        "p25": 0.07299526808306502,
        "median": 0.20151750556940565,
        "p75": 0.44198970413688654,
    },
}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _detect_m5_zones(frame: pd.DataFrame) -> tuple[SDZone, ...]:
    """Detect causal M5 imbalance zones; availability starts only after M5 close."""
    if frame.empty or len(frame) < 20:
        return ()
    work = frame.copy().reset_index(drop=True)
    work["atr14"] = _atr(work, 14)
    zones: list[SDZone] = []
    for i in range(16, len(work)):
        row = work.iloc[i]
        atr = _f(row.get("atr14"))
        if atr is None or atr <= 0:
            continue
        o, h, low, c = map(float, (row["open"], row["high"], row["low"], row["close"]))
        rng = max(h - low, 1e-12)
        body_fraction = abs(c - o) / rng
        range_atr = rng / atr
        if range_atr < M5_MIN_DEPARTURE_RANGE_ATR:
            continue
        if body_fraction < M5_MIN_DEPARTURE_BODY_FRACTION:
            continue
        direction = "LONG" if c > o else "SHORT" if c < o else ""
        if not direction:
            continue

        best: tuple[float, int, pd.DataFrame] | None = None
        for base_len in (1, 2, 3):
            start = i - base_len
            if start < 2:
                continue
            base = work.iloc[start:i]
            base_range = float(base["high"].max() - base["low"].min())
            base_range_atr = base_range / atr
            body_fracs = (
                (base["close"].astype(float) - base["open"].astype(float)).abs()
                / (base["high"].astype(float) - base["low"].astype(float)).clip(lower=1e-12)
            )
            compactness = base_range_atr + float(body_fracs.mean()) * 0.35
            if base_range_atr > M5_MAX_BASE_RANGE_ATR:
                continue
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base.copy())
        if best is None:
            continue

        _, base_len, base = best
        zlow, zhigh, proximal, distal = _base_geometry(base, direction)
        width = zhigh - zlow
        if width <= 0 or width / atr > M5_MAX_BASE_RANGE_ATR:
            continue
        pre_close = float(work.iloc[i - base_len - 1]["close"])
        pattern = _classify_pattern(
            direction=direction,
            pre_base_close=pre_close,
            base_mid=(zlow + zhigh) / 2.0,
        )
        departure_open = ensure_utc(pd.Timestamp(row["time"]).to_pydatetime())
        available_at = departure_open + timedelta(minutes=5)
        origin_at = ensure_utc(pd.Timestamp(base.iloc[0]["time"]).to_pydatetime())
        zones.append(
            SDZone(
                zone_id=_stable_sd_zone_id(
                    timeframe="M5",
                    direction=direction,
                    zone_class="IMBALANCE",
                    origin_at=origin_at,
                    available_at=available_at,
                    low=zlow,
                    high=zhigh,
                ),
                timeframe="M5",
                zone_class="IMBALANCE",
                pattern=pattern,
                direction=direction,
                low=zlow,
                high=zhigh,
                proximal=proximal,
                distal=distal,
                available_at=available_at,
                origin_at=origin_at,
                departure_at=available_at,
                atr_points=atr,
                base_bars=base_len,
                base_range_atr=width / atr,
                departure_range_atr=range_atr,
                departure_body_fraction=body_fraction,
                structural_bos=False,
            )
        )
    return tuple(zones)


def _overlap_ratio(a: SDZone, b: SDZone) -> float:
    overlap = max(0.0, min(float(a.high), float(b.high)) - max(float(a.low), float(b.low)))
    return overlap / max(float(a.high) - float(a.low), float(b.high) - float(b.low), 1e-12)


def _m5_superseded_at(zones: Sequence[SDZone]) -> dict[str, datetime | None]:
    result = {zone.zone_id: None for zone in zones}
    recent: dict[str, list[SDZone]] = {"LONG": [], "SHORT": []}
    for zone in sorted(zones, key=lambda z: (ensure_utc(z.available_at), z.zone_id)):
        now = ensure_utc(zone.available_at)
        bucket = recent[zone.direction]
        bucket[:] = [
            old for old in bucket
            if (now - ensure_utc(old.available_at)).total_seconds() / 60.0
            <= M5_SUPERSESSION_GAP_MINUTES + 1e-12
        ]
        for old in bucket:
            if result[old.zone_id] is None and _overlap_ratio(old, zone) >= M5_OVERLAP_REPLACE:
                result[old.zone_id] = now
        bucket.append(zone)
    return result


def _first_invalidation_map(
    price_m1: pd.DataFrame,
    zones: Sequence[SDZone],
    superseded: dict[str, datetime | None],
) -> dict[str, datetime | None]:
    timestamps = tuple(pd.Timestamp(v) for v in price_m1["timestamp"])
    closes = price_m1["close"].to_numpy(dtype=float, copy=False)
    out: dict[str, datetime | None] = {}
    for zone in zones:
        available = ensure_utc(zone.available_at)
        start = bisect_left(timestamps, pd.Timestamp(available))
        expiry = available + timedelta(hours=M5_ACTIVE_HOURS)
        replace_at = superseded.get(zone.zone_id)
        end_at = min(expiry, ensure_utc(replace_at)) if replace_at is not None else expiry
        end = bisect_left(timestamps, pd.Timestamp(end_at))
        if start >= len(timestamps) or end <= start:
            out[zone.zone_id] = None
            continue
        sample = closes[start:end]
        mask = sample < float(zone.distal) if zone.direction == "LONG" else sample > float(zone.distal)
        pos = np.flatnonzero(mask)
        out[zone.zone_id] = (
            None if len(pos) == 0
            else ensure_utc(timestamps[start + int(pos[0])].to_pydatetime())
        )
    return out


def _active_at(
    zone: SDZone,
    at: datetime,
    *,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> bool:
    point = ensure_utc(at)
    available = ensure_utc(zone.available_at)
    if available > point:
        return False
    if point > available + timedelta(hours=M5_ACTIVE_HOURS):
        return False
    replace = superseded.get(zone.zone_id)
    if replace is not None and ensure_utc(replace) <= point:
        return False
    invalid = invalidated.get(zone.zone_id)
    return invalid is None or ensure_utc(invalid) > point


def _contains(zone: SDZone, price: float) -> bool:
    return float(zone.low) <= float(price) <= float(zone.high)


def _width(zone: SDZone) -> float:
    return max(float(zone.high) - float(zone.low), 1e-12)



def _price_at_depth(zone: SDZone, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    width = _width(zone)
    return (
        float(zone.high) - d * width
        if zone.direction == "LONG"
        else float(zone.low) + d * width
    )


def _interval(low: float, high: float) -> tuple[float, float]:
    return (min(float(low), float(high)), max(float(low), float(high)))


def _m15_probability_geometry(parent: SDZone) -> dict[str, float]:
    prior = dict(V2252_M15_DEPTH_PRIOR[parent.direction])
    p25_price = _price_at_depth(parent, float(prior["p25"]))
    median_price = _price_at_depth(parent, float(prior["median"]))
    p75_price = _price_at_depth(parent, float(prior["p75"]))
    corridor_low, corridor_high = _interval(p25_price, p75_price)
    return {
        "p25_depth": float(prior["p25"]),
        "median_depth": float(prior["median"]),
        "p75_depth": float(prior["p75"]),
        "corridor_low": corridor_low,
        "corridor_high": corridor_high,
        "median_price": median_price,
    }


def _probability_weighted_m5_key(
    zone: SDZone,
    *,
    parent: SDZone,
) -> tuple[Any, ...]:
    """Rank M5 child without observing the later turning point.

    Priority is intentionally lexicographic rather than fitted:
    1) overlap the frozen V225.2 M15 p25–p75 reversal corridor,
    2) maximize the fraction of the M5 child inside that corridor,
    3) place M5 midpoint close to the frozen M15 median turning price,
    4) prefer a narrower child,
    5) prefer the most recently available child as the final tie-break.
    """
    geometry = _m15_probability_geometry(parent)
    corridor_low = float(geometry["corridor_low"])
    corridor_high = float(geometry["corridor_high"])
    overlap = max(
        0.0,
        min(float(zone.high), corridor_high) - max(float(zone.low), corridor_low),
    )
    child_width = _width(zone)
    parent_width = _width(parent)
    overlap_fraction = overlap / child_width
    midpoint = (float(zone.low) + float(zone.high)) / 2.0
    median_distance = abs(midpoint - float(geometry["median_price"])) / parent_width
    width_ratio = child_width / parent_width
    return (
        -int(overlap > 0.0),
        -overlap_fraction,
        median_distance,
        width_ratio,
        -ensure_utc(zone.available_at).timestamp(),
    )


def _m5_selection_diagnostic(zone: SDZone | None, *, parent: SDZone) -> dict[str, Any]:
    if zone is None:
        return {}
    geometry = _m15_probability_geometry(parent)
    corridor_low = float(geometry["corridor_low"])
    corridor_high = float(geometry["corridor_high"])
    overlap = max(
        0.0,
        min(float(zone.high), corridor_high) - max(float(zone.low), corridor_low),
    )
    midpoint = (float(zone.low) + float(zone.high)) / 2.0
    return {
        **geometry,
        "m5_low": float(zone.low),
        "m5_high": float(zone.high),
        "m5_width_ratio": _width(zone) / _width(parent),
        "corridor_overlap_fraction_of_m5": overlap / _width(zone),
        "midpoint_abs_distance_from_m15_median_as_parent_width": (
            abs(midpoint - float(geometry["median_price"])) / _width(parent)
        ),
    }


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    clean = sorted(float(v) for v in values if isfinite(float(v)) and 0 <= float(v) < 1)
    return {
        "p10": _quantile(clean, 0.10),
        "p25": _quantile(clean, 0.25),
        "p35": _quantile(clean, 0.35),
        "median": _quantile(clean, 0.50),
        "p60": _quantile(clean, 0.60),
        "p75": _quantile(clean, 0.75),
        "p85": _quantile(clean, 0.85),
        "p90": _quantile(clean, 0.90),
    }


def _ladder_report(depths: Sequence[float]) -> dict[str, Any]:
    clean = sorted(float(v) for v in depths if 0 <= float(v) < 1)
    if not clean:
        return {"n": 0, "depths": [], "any_fill_rate": None, "mean_filled_orders": None}
    levels = [float(np.quantile(np.array(clean), q)) for q in LADDER_QUANTILES]
    fills = [sum(depth + 1e-12 >= level for level in levels) for depth in clean]
    return {
        "n": len(clean),
        "quantiles": list(LADDER_QUANTILES),
        "depths": levels,
        "any_fill_rate": sum(v >= 1 for v in fills) / len(fills),
        "two_plus_fill_rate": sum(v >= 2 for v in fills) / len(fills),
        "three_plus_fill_rate": sum(v >= 3 for v in fills) / len(fills),
        "all_four_fill_rate": sum(v >= 4 for v in fills) / len(fills),
        "mean_filled_orders": sum(fills) / len(fills),
        "interpretation": (
            "Four equal 0.01-lot slots at successful-turning-depth quantiles "
            "q10/q35/q60/q85. This is a historical placement study, not execution authority."
        ),
    }


def build_year_records(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base_zones, episodes = build_depth_dataset(price_m1, target_year=target_year)
    zone_by_id = {z.zone_id: z for z in base_zones}
    m5_frame = _resample_ohlc(price_m1, "5min")
    m5_zones = _detect_m5_zones(m5_frame)
    superseded = _m5_superseded_at(m5_zones)
    invalidated = _first_invalidation_map(price_m1, m5_zones, superseded)

    h4_success = [
        row for row in episodes
        if row.timeframe == "H4" and row.reaction_hit and row.turning_price is not None
    ]
    m15_nested = [row for row in h4_success if row.m15_child_zone_id]
    records: list[dict[str, Any]] = []

    for row in m15_nested:
        parent = zone_by_id.get(str(row.m15_child_zone_id))
        if parent is None:
            continue
        active = [
            zone for zone in m5_zones
            if zone.direction == row.direction
            and _active_at(zone, row.touch_at, superseded=superseded, invalidated=invalidated)
            and _overlaps(parent, zone)
        ]
        naive_ranked = sorted(
            active,
            key=lambda z: (
                _width(z),
                -ensure_utc(z.available_at).timestamp(),
            ),
        )
        naive_selected = naive_ranked[0] if naive_ranked else None
        probability_ranked = sorted(
            active,
            key=lambda z: _probability_weighted_m5_key(z, parent=parent),
        )
        selected = probability_ranked[0] if probability_ranked else None
        capturing = [z for z in active if _contains(z, float(row.turning_price))]
        capturing.sort(key=lambda z: (_width(z), -ensure_utc(z.available_at).timestamp()))
        oracle = capturing[0] if capturing else None
        naive_capture = bool(
            naive_selected and _contains(naive_selected, float(row.turning_price))
        )
        selected_capture = bool(selected and _contains(selected, float(row.turning_price)))
        selected_depth = (
            normalized_depth(selected, float(row.turning_price))
            if selected_capture and selected is not None else None
        )
        records.append(
            {
                "year": int(target_year),
                "touch_at": ensure_utc(row.touch_at).isoformat(),
                "direction": row.direction,
                "h4_zone_id": row.zone_id,
                "h1_child_zone_id": row.h1_child_zone_id,
                "m15_child_zone_id": row.m15_child_zone_id,
                "turning_price": float(row.turning_price),
                "h4_turning_depth": row.turning_depth,
                "m15_turning_depth": row.m15_child_depth,
                "active_m5_candidates": len(active),
                "oracle_m5_capture": oracle is not None,
                "naive_m5_zone_id": (
                    None if naive_selected is None else naive_selected.zone_id
                ),
                "naive_m5_capture": naive_capture,
                "selected_m5_zone_id": None if selected is None else selected.zone_id,
                "selected_m5_selector": "V2252_M15_IQR_MEDIAN_WEIGHTED_LEXICOGRAPHIC",
                "selected_m5_diagnostic": _m5_selection_diagnostic(
                    selected,
                    parent=parent,
                ),
                "selected_m5_capture": selected_capture,
                "selected_m5_depth": selected_depth,
                "selected_m5_internal_depth": (
                    None if not selected_capture or selected is None
                    else normalized_internal_depth(selected, float(row.turning_price))
                ),
                "m15_width": _width(parent),
                "selected_m5_width": None if selected is None else _width(selected),
                "m5_to_m15_width_ratio": (
                    None if selected is None else _width(selected) / _width(parent)
                ),
                "selected_m5_available_lead_minutes": (
                    None if selected is None
                    else (ensure_utc(row.touch_at) - ensure_utc(selected.available_at)).total_seconds() / 60.0
                ),
            }
        )

    summary = summarize_records(
        records,
        h4_successes=len(h4_success),
        h1_nested=sum(1 for row in h4_success if row.h1_child_zone_id),
        m15_nested=len(m15_nested),
        m5_zone_count=len(m5_zones),
    )
    return summary, records


def summarize_records(
    records: Sequence[dict[str, Any]],
    *,
    h4_successes: int,
    h1_nested: int,
    m15_nested: int,
    m5_zone_count: int,
) -> dict[str, Any]:
    rows = list(records)
    available = [r for r in rows if int(r.get("active_m5_candidates") or 0) > 0]
    oracle = [r for r in rows if bool(r.get("oracle_m5_capture"))]
    naive = [r for r in rows if bool(r.get("naive_m5_capture"))]
    selected = [r for r in rows if bool(r.get("selected_m5_capture"))]
    depths = [float(r["selected_m5_depth"]) for r in selected if r.get("selected_m5_depth") is not None]
    ratios = [float(r["m5_to_m15_width_ratio"]) for r in available if r.get("m5_to_m15_width_ratio") is not None]
    leads = [float(r["selected_m5_available_lead_minutes"]) for r in available if r.get("selected_m5_available_lead_minutes") is not None]
    return {
        "h4_successes": int(h4_successes),
        "h1_nested": int(h1_nested),
        "m15_nested": int(m15_nested),
        "m5_zone_count": int(m5_zone_count),
        "m5_available_given_m15": len(available),
        "m5_available_rate_given_m15": None if not m15_nested else len(available) / m15_nested,
        "oracle_m5_capture_given_m15": None if not m15_nested else len(oracle) / m15_nested,
        "naive_m5_capture_given_available": None if not available else len(naive) / len(available),
        "naive_m5_capture_given_m15": None if not m15_nested else len(naive) / m15_nested,
        "selected_m5_capture_given_available": None if not available else len(selected) / len(available),
        "selected_m5_capture_given_m15": None if not m15_nested else len(selected) / m15_nested,
        "selected_m5_depth_quantiles": _quantiles(depths),
        "selected_m5_ladder": _ladder_report(depths),
        "median_m5_to_m15_width_ratio": None if not ratios else median(ratios),
        "median_m5_available_lead_minutes": None if not leads else median(leads),
        "coverage_contract": (
            "M5_AVAILABLE uses only zones known and active at H4 touch. "
            "ORACLE_CAPTURE asks whether any such M5 child contains the later turn. "
            "NAIVE_CAPTURE is the old narrowest/most-recent selector. SELECTED_CAPTURE "
            "uses the frozen V225.2 M15 p25-p75 corridor and median before width/recency, "
            "without observing the later turn. Both remain conditional on the V225 "
            "descriptive M15 parent and are not a fully "
            "walk-forward strategy estimate."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }

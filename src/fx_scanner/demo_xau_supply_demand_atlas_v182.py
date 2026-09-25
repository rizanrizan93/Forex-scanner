from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .config import load_project_config
from .demo_xau_afic_path_shadow_observer import (
    OriginZone,
    _atr,
    _origin_zones,
    _resample_completed,
)
from .demo_xau_premap_candidate_v181 import (
    _latest_completed_levels,
    _latest_worker_details,
)
from .demo_xau_m5_bidirectional_path_v196 import (
    evaluate_bidirectional_m5_path,
)
from .demo_xau_zone_reuse_v200 import evaluate_bidirectional_reuse
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_supply_demand_atlas_v182"
CONTRACT = "XAU_HTF_SUPPLY_DEMAND_ATLAS_V182"
REQUEST_COUNT = 3000
LOOKBACK_DAYS = 45
MAX_DISPLAY_ZONES = 12
M5_REQUEST_COUNT = 1800
M5_LOOKBACK_DAYS = 10

TIMEFRAME_RULES = {
    "H1": "1h",
    "H4": "4h",
    "D1": "1D",
}
TIMEFRAME_PRIORITY = {"D1": 3, "H4": 2, "H1": 1}
ROUND_STEP_USD = 10.0
LIQUIDITY_NEAR_ATR = 0.30

MIN_DEPARTURE_RANGE_ATR = {
    "H1": 0.95,
    "H4": 0.85,
    "D1": 0.80,
}
MIN_DEPARTURE_BODY_FRACTION = {
    "H1": 0.48,
    "H4": 0.45,
    "D1": 0.42,
}
MAX_BASE_RANGE_ATR = {
    "H1": 1.30,
    "H4": 1.35,
    "D1": 1.40,
}


@dataclass(frozen=True, slots=True)
class SDZone:
    zone_id: str
    timeframe: str
    zone_class: str
    pattern: str
    direction: str
    low: float
    high: float
    proximal: float
    distal: float
    available_at: datetime
    origin_at: datetime
    departure_at: datetime
    atr_points: float
    base_bars: int
    base_range_atr: float
    departure_range_atr: float
    departure_body_fraction: float
    structural_bos: bool


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _stable_sd_zone_id(
    *,
    timeframe: str,
    direction: str,
    zone_class: str,
    origin_at: datetime,
    available_at: datetime,
    low: float,
    high: float,
) -> str:
    raw = "|".join(
        (
            timeframe,
            direction,
            zone_class,
            ensure_utc(origin_at).isoformat(),
            ensure_utc(available_at).isoformat(),
            f"{float(low):.8f}",
            f"{float(high):.8f}",
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _age_bucket(timeframe: str, age_hours: float) -> str:
    tf = str(timeframe).upper()
    hours = max(0.0, float(age_hours))
    if tf == "H1":
        if hours <= 24:
            return "H1_0_24H"
        if hours <= 48:
            return "H1_24_48H"
        if hours <= 96:
            return "H1_48_96H"
        return "H1_GT_96H"
    bar_hours = 4.0 if tf == "H4" else 24.0
    bars = hours / bar_hours
    if tf == "H4":
        if bars <= 6:
            return "H4_0_6_BARS"
        if bars <= 12:
            return "H4_6_12_BARS"
        if bars <= 24:
            return "H4_12_24_BARS"
        return "H4_GT_24_BARS"
    if bars <= 3:
        return "D1_0_3_BARS"
    if bars <= 7:
        return "D1_3_7_BARS"
    if bars <= 14:
        return "D1_7_14_BARS"
    return "D1_GT_14_BARS"


def _session_bucket_wib(timestamp: datetime) -> str:
    hour = ensure_utc(timestamp).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Jakarta")
    ).hour
    minute = ensure_utc(timestamp).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Jakarta")
    ).minute
    hm = hour * 60 + minute
    if 17 * 60 <= hm < 19 * 60 + 30:
        return "PRE_NY_1700_1929_WIB"
    if 19 * 60 + 30 <= hm < 20 * 60 + 30:
        return "US_MACRO_WINDOW_1930_2029_WIB"
    if 20 * 60 + 30 <= hm < 22 * 60 + 30:
        return "NY_OPEN_2030_2229_WIB"
    return "OTHER_WIB"


def _distance_to_zone(price: float, low: float, high: float) -> float:
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _correct_side(price: float, zone: SDZone) -> bool:
    if zone.direction == "LONG":
        return price >= zone.low
    return price <= zone.high


def _classify_pattern(
    *,
    direction: str,
    pre_base_close: float,
    base_mid: float,
) -> str:
    if direction == "LONG":
        return "DBR" if pre_base_close > base_mid else "RBR"
    return "RBD" if pre_base_close < base_mid else "DBD"


def _base_geometry(base: pd.DataFrame, direction: str) -> tuple[float, float, float, float]:
    low = float(base["low"].min())
    high = float(base["high"].max())
    body_high = float(pd.concat([base["open"], base["close"]], axis=1).max(axis=1).max())
    body_low = float(pd.concat([base["open"], base["close"]], axis=1).min(axis=1).min())
    if direction == "LONG":
        proximal = min(high, body_high)
        distal = low
    else:
        proximal = max(low, body_low)
        distal = high
    return low, high, proximal, distal


def _detect_base_departure_zones(
    frame: pd.DataFrame,
    *,
    timeframe: str,
) -> tuple[SDZone, ...]:
    if frame.empty or len(frame) < 20:
        return ()
    work = frame.copy().reset_index(drop=True)
    work["atr14"] = _atr(work, 14)
    zones: list[SDZone] = []

    for i in range(16, len(work)):
        row = work.iloc[i]
        atr = _safe_float(row.get("atr14"))
        if atr is None or atr <= 0:
            continue
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        rng = max(h - l, 1e-12)
        body_fraction = abs(c - o) / rng
        range_atr = rng / atr
        if range_atr < MIN_DEPARTURE_RANGE_ATR[timeframe]:
            continue
        if body_fraction < MIN_DEPARTURE_BODY_FRACTION[timeframe]:
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
            if base_range_atr > MAX_BASE_RANGE_ATR[timeframe]:
                continue
            if best is None or compactness < best[0]:
                best = (compactness, base_len, base.copy())
        if best is None:
            continue

        _, base_len, base = best
        low, high, proximal, distal = _base_geometry(base, direction)
        width = high - low
        if width <= 0 or width / atr > MAX_BASE_RANGE_ATR[timeframe]:
            continue

        pre_close = float(work.iloc[i - base_len - 1]["close"])
        base_mid = (low + high) / 2.0
        pattern = _classify_pattern(
            direction=direction,
            pre_base_close=pre_close,
            base_mid=base_mid,
        )
        available_at = ensure_utc(row["time"].to_pydatetime())
        origin_at = ensure_utc(base.iloc[0]["time"].to_pydatetime())
        zone_id = _stable_sd_zone_id(
            timeframe=timeframe,
            direction=direction,
            zone_class="IMBALANCE",
            origin_at=origin_at,
            available_at=available_at,
            low=low,
            high=high,
        )
        zones.append(
            SDZone(
                zone_id=zone_id,
                timeframe=timeframe,
                zone_class="IMBALANCE",
                pattern=pattern,
                direction=direction,
                low=low,
                high=high,
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


def _structural_h1_zones(
    rows: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[SDZone, ...]:
    out: list[SDZone] = []
    for zone in _origin_zones(rows, as_of=as_of):
        low = float(zone.low)
        high = float(zone.high)
        direction = str(zone.direction)
        if direction == "LONG":
            proximal = high
            distal = low
            pattern = "STRUCTURAL_DEMAND"
        else:
            proximal = low
            distal = high
            pattern = "STRUCTURAL_SUPPLY"
        zone_id = _stable_sd_zone_id(
            timeframe="H1",
            direction=direction,
            zone_class="STRUCTURAL",
            origin_at=zone.origin_at,
            available_at=zone.available_at,
            low=low,
            high=high,
        )
        out.append(
            SDZone(
                zone_id=zone_id,
                timeframe="H1",
                zone_class="STRUCTURAL",
                pattern=pattern,
                direction=direction,
                low=low,
                high=high,
                proximal=proximal,
                distal=distal,
                available_at=ensure_utc(zone.available_at),
                origin_at=ensure_utc(zone.origin_at),
                departure_at=ensure_utc(zone.bos_at),
                atr_points=float(zone.h1_atr),
                base_bars=1,
                base_range_atr=max(0.0, (high - low) / float(zone.h1_atr)),
                departure_range_atr=float(zone.displacement_range_atr),
                departure_body_fraction=float(zone.displacement_body_fraction),
                structural_bos=True,
            )
        )
    return tuple(out)


def _overlap_ratio(a: SDZone, b: SDZone) -> float:
    overlap = max(0.0, min(a.high, b.high) - max(a.low, b.low))
    width = max(min(a.high - a.low, b.high - b.low), 1e-12)
    return overlap / width


def _dedupe_zones(zones: Sequence[SDZone]) -> tuple[SDZone, ...]:
    ordered = sorted(
        zones,
        key=lambda z: (
            TIMEFRAME_PRIORITY.get(z.timeframe, 0),
            z.available_at,
            z.zone_class == "STRUCTURAL",
        ),
        reverse=True,
    )
    kept: list[SDZone] = []
    for zone in ordered:
        duplicate = False
        for existing in kept:
            if existing.timeframe != zone.timeframe or existing.direction != zone.direction:
                continue
            max_time_gap = 4.1 if zone.timeframe == "H4" else 24.1 if zone.timeframe == "D1" else 1.1
            gap_hours = abs(
                (ensure_utc(existing.available_at) - ensure_utc(zone.available_at)).total_seconds()
            ) / 3600.0
            if gap_hours <= max_time_gap and _overlap_ratio(existing, zone) >= 0.70:
                duplicate = True
                break
        if not duplicate:
            kept.append(zone)
    return tuple(kept)


def _zone_lifecycle(
    zone: SDZone,
    *,
    bars: Sequence[Bar],
) -> dict[str, Any]:
    touches = 0
    first_touch_at: datetime | None = None
    last_touch_at: datetime | None = None
    invalidated_at: datetime | None = None
    max_mitigation = 0.0
    was_inside = False
    width = max(zone.high - zone.low, 1e-12)

    for bar in sorted(tuple(bars), key=lambda x: ensure_utc(x.timestamp)):
        ts = ensure_utc(bar.timestamp)
        if ts < ensure_utc(zone.available_at):
            continue
        inside = float(bar.high) >= zone.low and float(bar.low) <= zone.high
        if inside and not was_inside:
            touches += 1
            if first_touch_at is None:
                first_touch_at = ts
            last_touch_at = ts
        elif inside:
            last_touch_at = ts

        if inside:
            if zone.direction == "LONG":
                penetration = (zone.high - max(zone.low, float(bar.low))) / width
            else:
                penetration = (min(zone.high, float(bar.high)) - zone.low) / width
            max_mitigation = max(max_mitigation, min(1.0, max(0.0, penetration)))

        if zone.direction == "LONG" and float(bar.close) < zone.distal:
            invalidated_at = ts
            break
        if zone.direction == "SHORT" and float(bar.close) > zone.distal:
            invalidated_at = ts
            break
        was_inside = inside

    if invalidated_at is not None:
        freshness = "BROKEN"
    elif touches == 0:
        freshness = "FRESH"
    elif max_mitigation >= 0.75:
        freshness = "DEEPLY_MITIGATED"
    elif max_mitigation >= 0.35:
        freshness = "PARTIALLY_MITIGATED"
    elif touches == 1:
        freshness = "FIRST_TEST"
    elif touches == 2:
        freshness = "SECOND_TEST"
    else:
        freshness = "MULTI_TESTED"

    return {
        "touch_count": touches,
        "first_touch_at": None if first_touch_at is None else first_touch_at.isoformat(),
        "last_touch_at": None if last_touch_at is None else last_touch_at.isoformat(),
        "invalidated_at": None if invalidated_at is None else invalidated_at.isoformat(),
        "mitigation_depth": round(max_mitigation, 4),
        "freshness": freshness,
        "active": invalidated_at is None,
    }


def _generic_liquidity_evidence(
    zone: SDZone,
    *,
    levels: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    atr = max(float(zone.atr_points), 1e-12)
    boundary = zone.proximal
    relevant = "LOW" if zone.direction == "LONG" else "HIGH"
    threshold = LIQUIDITY_NEAR_ATR * atr
    nearby: list[dict[str, Any]] = []

    for item in levels:
        source = str(item.get("source") or "")
        if relevant not in source:
            continue
        price = _safe_float(item.get("price"))
        if price is None:
            continue
        distance = abs(price - boundary)
        if distance <= threshold:
            nearby.append(
                {
                    "source": source,
                    "price": price,
                    "distance_atr": distance / atr,
                }
            )

    round_level = round(boundary / ROUND_STEP_USD) * ROUND_STEP_USD
    round_distance = abs(round_level - boundary)
    if round_distance <= threshold:
        nearby.append(
            {
                "source": "ROUND_NUMBER",
                "price": round_level,
                "distance_atr": round_distance / atr,
            }
        )

    dedup: dict[str, dict[str, Any]] = {}
    for item in nearby:
        key = str(item["source"])
        if key not in dedup or float(item["distance_atr"]) < float(dedup[key]["distance_atr"]):
            dedup[key] = item
    selected = sorted(dedup.values(), key=lambda x: float(x["distance_atr"]))
    return {
        "confluence_count": len(selected),
        "sources": [str(x["source"]) for x in selected[:8]],
        "nearby_levels": selected[:8],
    }


def _approach_quality(
    rows: Sequence[Bar],
    *,
    zone: SDZone,
) -> dict[str, Any]:
    data = tuple(sorted(tuple(rows), key=lambda x: ensure_utc(x.timestamp)))[-12:]
    if len(data) < 7:
        return {
            "state": "INSUFFICIENT",
            "toward_progress_atr": None,
            "efficiency": None,
            "range_acceleration": None,
            "directional_close_fraction": None,
        }

    closes = np.asarray([float(x.close) for x in data], dtype=float)
    ranges = np.asarray([max(float(x.high) - float(x.low), 1e-12) for x in data], dtype=float)
    diffs = np.diff(closes)
    net = float(closes[-1] - closes[0])
    toward = (-net if zone.direction == "LONG" else net) / max(zone.atr_points, 1e-12)
    efficiency = abs(net) / max(float(np.abs(diffs).sum()), 1e-12)
    recent = float(ranges[-3:].mean())
    prior = float(ranges[-6:-3].mean())
    acceleration = recent / max(prior, 1e-12)
    if zone.direction == "LONG":
        directional = float(np.mean(diffs[-6:] < 0))
    else:
        directional = float(np.mean(diffs[-6:] > 0))

    if toward >= 0.80 and acceleration >= 1.15 and directional >= 0.67:
        state = "AGGRESSIVE_APPROACH"
    elif toward >= 0.15 and acceleration < 1.15:
        state = "CONTROLLED_APPROACH"
    elif toward > 0:
        state = "APPROACHING"
    else:
        state = "FLAT_OR_AWAY"

    return {
        "state": state,
        "toward_progress_atr": round(toward, 4),
        "efficiency": round(efficiency, 4),
        "range_acceleration": round(acceleration, 4),
        "directional_close_fraction": round(directional, 4),
    }


def _strategic_alignment(direction: str, strategic_bias: str) -> str:
    bias = str(strategic_bias or "NEUTRAL").upper()
    if bias not in {"LONG", "SHORT"}:
        return "NETRAL"
    return "SEARAH" if direction == bias else "BERLAWANAN"


def _nesting(
    zone: SDZone,
    active_zones: Sequence[SDZone],
) -> tuple[int, tuple[str, ...]]:
    current_priority = TIMEFRAME_PRIORITY.get(zone.timeframe, 0)
    midpoint = (zone.low + zone.high) / 2.0
    parents: list[str] = []
    for parent in active_zones:
        if parent.zone_id == zone.zone_id or parent.direction != zone.direction:
            continue
        if TIMEFRAME_PRIORITY.get(parent.timeframe, 0) <= current_priority:
            continue
        if parent.low <= midpoint <= parent.high or _overlap_ratio(zone, parent) > 0:
            parents.append(f"{parent.timeframe}:{parent.zone_id}")
    return len(parents), tuple(parents)


def _research_score(
    *,
    zone: SDZone,
    lifecycle: dict[str, Any],
    distance_atr: float,
    nesting_count: int,
    liquidity_count: int,
    alignment: str,
) -> float:
    departure = min(20.0, max(0.0, zone.departure_range_atr) / 2.0 * 20.0)
    body = min(10.0, max(0.0, zone.departure_body_fraction) / 0.80 * 10.0)
    compact = max(0.0, 1.0 - min(zone.base_range_atr, 1.5) / 1.5) * 10.0
    structural = 15.0 if zone.structural_bos else 7.5
    freshness_map = {
        "FRESH": 15.0,
        "FIRST_TEST": 11.0,
        "SECOND_TEST": 7.0,
        "PARTIALLY_MITIGATED": 5.0,
        "DEEPLY_MITIGATED": 2.0,
        "MULTI_TESTED": 2.0,
        "BROKEN": 0.0,
    }
    freshness = freshness_map.get(str(lifecycle.get("freshness") or ""), 0.0)
    nesting = min(10.0, nesting_count * 5.0)
    liquidity = min(10.0, liquidity_count * 2.5)
    proximity = max(0.0, 1.0 - min(distance_atr, 3.0) / 3.0) * 10.0
    align = 5.0 if alignment == "SEARAH" else 2.5 if alignment == "NETRAL" else 0.0
    return round(
        min(100.0, departure + body + compact + structural + freshness + nesting + liquidity + proximity + align),
        2,
    )



def _active_payloads(payloads: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(
        item
        for item in payloads
        if bool(dict(item.get("lifecycle") or {}).get("active"))
    )


def _freshness_rank(item: dict[str, Any]) -> int:
    freshness = str(dict(item.get("lifecycle") or {}).get("freshness") or "")
    return {
        "FRESH": 6,
        "FIRST_TEST": 5,
        "SECOND_TEST": 4,
        "PARTIALLY_MITIGATED": 3,
        "DEEPLY_MITIGATED": 2,
        "MULTI_TESTED": 1,
        "BROKEN": 0,
    }.get(freshness, 0)


def _precision_timeframe_rank(item: dict[str, Any]) -> int:
    # Reaction routing prefers H1 precision. H4/D1 remain parent context.
    return {"H1": 3, "H4": 2, "D1": 1}.get(
        str(item.get("timeframe") or "").upper(),
        0,
    )


def _source_zone_stack(
    payloads: Sequence[dict[str, Any]],
    *,
    direction: str,
    last_price: float,
) -> tuple[dict[str, Any], ...]:
    candidates = [
        item
        for item in payloads
        if str(item.get("direction") or "") == direction
        and bool(item.get("correct_side"))
    ]
    if not candidates:
        return ()

    in_price = [
        item
        for item in candidates
        if float(item["low"]) <= float(last_price) <= float(item["high"])
    ]
    pool = in_price if in_price else candidates
    pool.sort(
        key=lambda item: (
            0 if float(item.get("distance_points") or 0.0) == 0 else 1,
            float(item.get("distance_points") or 0.0),
            -_precision_timeframe_rank(item),
            -int(item.get("htf_nesting_count") or 0),
            -_freshness_rank(item),
            0 if bool(item.get("structural_bos")) else 1,
            -float(item.get("research_score") or 0.0),
        )
    )
    return tuple(pool[:8])


def _true_nearest_zone(
    payloads: Sequence[dict[str, Any]],
    *,
    direction: str,
    last_price: float | None = None,
) -> dict[str, Any] | None:
    if last_price is not None:
        stack = _source_zone_stack(
            payloads,
            direction=direction,
            last_price=float(last_price),
        )
        return None if not stack else stack[0]
    candidates = [
        item
        for item in payloads
        if str(item.get("direction") or "") == direction
        and bool(item.get("correct_side"))
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            float(item.get("distance_points") or 0.0),
            -_precision_timeframe_rank(item),
            -int(item.get("htf_nesting_count") or 0),
            -_freshness_rank(item),
            -float(item.get("research_score") or 0.0),
        )
    )
    return candidates[0]


def _zone_mid(item: dict[str, Any]) -> float:
    return (float(item["low"]) + float(item["high"])) / 2.0


def _compact_path_zone(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
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
        "available_at",
        "origin_at",
        "departure_at",
        "status",
        "age_bucket",
        "distance_points",
        "distance_atr",
        "atr_points",
        "research_score",
        "htf_nesting_count",
        "strategic_alignment",
        "session_context",
    )
    out = {key: item.get(key) for key in keys}
    out["lifecycle"] = dict(item.get("lifecycle") or {})
    out["approach"] = dict(item.get("approach") or {})
    out["liquidity"] = dict(item.get("liquidity") or {})
    out["nested_in"] = list(item.get("nested_in") or [])
    return out


def _path_internal_targets(
    *,
    levels: Sequence[dict[str, Any]],
    direction: str,
    start_price: float,
    end_price: float,
) -> tuple[dict[str, Any], ...]:
    low = min(float(start_price), float(end_price))
    high = max(float(start_price), float(end_price))
    wanted_role = "HIGH" if direction == "LONG" else "LOW"
    output: list[dict[str, Any]] = []

    for level in levels:
        source = str(level.get("source") or "")
        price = _safe_float(level.get("price"))
        if price is None or not (low < price < high):
            continue
        if source.startswith("H1_SWING_"):
            if not source.endswith(wanted_role):
                continue
        elif wanted_role not in source:
            continue
        output.append(
            {
                "source": source,
                "price": float(price),
                "distance_from_start": abs(float(price) - float(start_price)),
            }
        )

    first_round = int(low // ROUND_STEP_USD) * int(ROUND_STEP_USD)
    for value in range(first_round, int(high) + int(ROUND_STEP_USD), int(ROUND_STEP_USD)):
        price = float(value)
        if low < price < high:
            output.append(
                {
                    "source": "ROUND_NUMBER",
                    "price": price,
                    "distance_from_start": abs(price - float(start_price)),
                }
            )

    dedup: dict[tuple[str, float], dict[str, Any]] = {}
    for item in output:
        key = (str(item["source"]), round(float(item["price"]), 4))
        dedup[key] = item
    ordered = sorted(
        dedup.values(),
        key=lambda item: float(item["distance_from_start"]),
    )
    return tuple(ordered[:8])


def _opposing_zone_candidates(
    payloads: Sequence[dict[str, Any]],
    *,
    source: dict[str, Any],
    reaction_direction: str,
) -> tuple[dict[str, Any], ...]:
    source_low = float(source["low"])
    source_high = float(source["high"])
    wanted = "SHORT" if reaction_direction == "LONG" else "LONG"
    candidates: list[dict[str, Any]] = []
    for item in payloads:
        if str(item.get("direction") or "") != wanted:
            continue
        item_low = float(item["low"])
        item_high = float(item["high"])
        # Opposing destination must be fully ahead of the source zone.
        # Partial overlap is context/confluence, not a valid path destination.
        if reaction_direction == "LONG" and item_low <= source_high:
            continue
        if reaction_direction == "SHORT" and item_high >= source_low:
            continue
        candidates.append(item)

    def path_gap(item: dict[str, Any]) -> float:
        if reaction_direction == "LONG":
            return max(0.0, float(item["low"]) - source_high)
        return max(0.0, source_low - float(item["high"]))

    candidates.sort(
        key=lambda item: (
            path_gap(item),
            -TIMEFRAME_PRIORITY.get(str(item.get("timeframe") or ""), 0),
            -float(item.get("research_score") or 0.0),
        )
    )
    return tuple(candidates[:5])


def _build_directional_path(
    *,
    source: dict[str, Any] | None,
    reaction_direction: str,
    active_payloads: Sequence[dict[str, Any]],
    levels: Sequence[dict[str, Any]],
    last_price: float,
) -> dict[str, Any] | None:
    if not source:
        return None
    opponents = _opposing_zone_candidates(
        active_payloads,
        source=source,
        reaction_direction=reaction_direction,
    )
    primary = opponents[0] if opponents else None

    source_low = float(source["low"])
    source_high = float(source["high"])
    in_source = source_low <= float(last_price) <= source_high
    if reaction_direction == "LONG":
        # Waypoints begin after price has reclaimed the demand proximal boundary;
        # levels still inside demand are not reaction targets.
        start_price = max(float(last_price), source_high)
        end_price = float(primary["low"]) if primary else start_price
    else:
        # Mirror rule for supply: targets begin below the supply proximal boundary.
        start_price = min(float(last_price), source_low)
        end_price = float(primary["high"]) if primary else start_price

    internal_targets = (
        ()
        if primary is None
        else _path_internal_targets(
            levels=levels,
            direction=reaction_direction,
            start_price=start_price,
            end_price=end_price,
        )
    )
    reaction_target: dict[str, Any] | None = None
    reaction_target_basis = None
    if internal_targets:
        reaction_target = dict(internal_targets[-1])
        reaction_target["role"] = "REACTION_TARGET"
        reaction_target_basis = "LAST_INTERNAL_WAYPOINT_BEFORE_OPPOSING_ZONE"
    elif primary is not None:
        fallback_price = (
            float(primary["low"])
            if reaction_direction == "LONG"
            else float(primary["high"])
        )
        reaction_target = {
            "source": "OPPOSING_ZONE_PROXIMAL_FALLBACK",
            "price": fallback_price,
            "distance_from_start": abs(fallback_price - float(start_price)),
            "role": "REACTION_TARGET",
        }
        reaction_target_basis = "OPPOSING_ZONE_PROXIMAL_FALLBACK"

    checkpoint_targets = [
        {**dict(item), "role": "CHECKPOINT"}
        for item in internal_targets[:-1]
    ]
    target_ladder = list(checkpoint_targets)
    if reaction_target is not None:
        target_ladder.append(reaction_target)
    if primary is not None:
        target_ladder.append(
            {
                "role": "TERMINAL_OPPOSING_ZONE",
                "low": float(primary["low"]),
                "high": float(primary["high"]),
                "zone_id": primary.get("zone_id"),
                "timeframe": primary.get("timeframe"),
            }
        )

    state = (
        "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION"
        if in_source
        else "SOURCE_ZONE_APPROACHING"
        if float(source.get("distance_atr") or 999.0) <= 0.75
        else "SOURCE_ZONE_WATCH"
    )
    return {
        "state": state,
        "source_zone": _compact_path_zone(source),
        "reaction_direction": reaction_direction,
        "primary_opposing_zone": _compact_path_zone(primary),
        "destination_stack": [
            _compact_path_zone(item) for item in opponents[:5]
        ],
        "secondary_opposing_zones": [
            _compact_path_zone(item) for item in opponents[1:4]
        ],
        "internal_targets": list(internal_targets),
        "checkpoint_targets": checkpoint_targets,
        "reaction_target": reaction_target,
        "reaction_target_basis": reaction_target_basis,
        "terminal_target_zone": _compact_path_zone(primary),
        "target_ladder": target_ladder,
        "path_distance_points": None
        if primary is None
        else round(abs(_zone_mid(primary) - _zone_mid(source)), 4),
        "confirmation_required": (
            "SWEEP_OR_MITIGATION_THEN_M5_M15_RECLAIM_MSS_OR_DISPLACEMENT"
        ),
        "execution_influence": False,
        "execution_authority": False,
        "note": (
            "Reaction target is the final internal waypoint before the first fully forward "
            "opposing zone when available; otherwise the opposing proximal boundary is used. "
            "This is a forecast objective, not a guaranteed target."
        ),
    }


def _build_path_map(
    *,
    payloads: Sequence[dict[str, Any]],
    levels: Sequence[dict[str, Any]],
    last_price: float,
) -> dict[str, Any]:
    active_payloads = _active_payloads(payloads)
    demand_stack = _source_zone_stack(
        active_payloads,
        direction="LONG",
        last_price=last_price,
    )
    supply_stack = _source_zone_stack(
        active_payloads,
        direction="SHORT",
        last_price=last_price,
    )
    nearest_demand = None if not demand_stack else demand_stack[0]
    nearest_supply = None if not supply_stack else supply_stack[0]
    demand_to_supply = _build_directional_path(
        source=nearest_demand,
        reaction_direction="LONG",
        active_payloads=active_payloads,
        levels=levels,
        last_price=last_price,
    )
    supply_to_demand = _build_directional_path(
        source=nearest_supply,
        reaction_direction="SHORT",
        active_payloads=active_payloads,
        levels=levels,
        last_price=last_price,
    )

    active_path = None
    for candidate in (demand_to_supply, supply_to_demand):
        if candidate and candidate.get("state") == "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION":
            active_path = candidate
            break
    if active_path is None:
        entered = []
        for candidate in (demand_to_supply, supply_to_demand):
            if not candidate:
                continue
            source_zone = dict(candidate.get("source_zone") or {})
            distance_atr = _safe_float(source_zone.get("distance_atr"))
            if distance_atr is not None:
                entered.append((distance_atr, candidate))
        if entered:
            entered.sort(key=lambda item: item[0])
            active_path = entered[0][1]

    return {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "nearest_demand": _compact_path_zone(nearest_demand),
        "nearest_supply": _compact_path_zone(nearest_supply),
        "demand_source_stack": [
            _compact_path_zone(item) for item in demand_stack[:5]
        ],
        "supply_source_stack": [
            _compact_path_zone(item) for item in supply_stack[:5]
        ],
        "demand_to_supply": demand_to_supply,
        "supply_to_demand": supply_to_demand,
        "active_path": active_path,
        "execution_influence": False,
        "execution_authority": False,
    }


def evaluate_supply_demand_atlas(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    strategic_bias: str = "NEUTRAL",
) -> dict[str, Any]:
    now = ensure_utc(as_of)
    rows = tuple(
        row
        for row in sorted(tuple(bars), key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= now
    )
    if len(rows) < 300:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_HISTORY",
            "execution_influence": False,
            "execution_authority": False,
            "zones": [],
        }

    last_price = float(rows[-1].close)
    levels = _latest_completed_levels(rows, as_of=now)
    zones: list[SDZone] = list(_structural_h1_zones(rows, as_of=now))
    timeframe_counts: dict[str, int] = {}

    for timeframe, rule in TIMEFRAME_RULES.items():
        frame = _resample_completed(rows, rule, as_of=now)
        detected = _detect_base_departure_zones(frame, timeframe=timeframe)
        zones.extend(detected)
        timeframe_counts[timeframe] = len(detected)

    zones = list(_dedupe_zones(zones))
    lifecycle_by_id = {
        zone.zone_id: _zone_lifecycle(zone, bars=rows)
        for zone in zones
    }
    active = [
        zone for zone in zones
        if bool(lifecycle_by_id[zone.zone_id].get("active"))
    ]

    payloads: list[dict[str, Any]] = []
    for zone in zones:
        lifecycle = lifecycle_by_id[zone.zone_id]
        age_hours = max(0.0, (now - ensure_utc(zone.available_at)).total_seconds() / 3600.0)
        distance_points = _distance_to_zone(last_price, zone.low, zone.high)
        distance_atr = distance_points / max(zone.atr_points, 1e-12)
        liquidity = _generic_liquidity_evidence(zone, levels=levels)
        nesting_count, nested_in = _nesting(zone, active)
        alignment = _strategic_alignment(zone.direction, strategic_bias)
        approach = _approach_quality(rows, zone=zone)
        correct_side = _correct_side(last_price, zone)
        score = _research_score(
            zone=zone,
            lifecycle=lifecycle,
            distance_atr=distance_atr,
            nesting_count=nesting_count,
            liquidity_count=int(liquidity.get("confluence_count") or 0),
            alignment=alignment,
        )
        status = (
            "BROKEN_RESEARCH_ONLY"
            if not lifecycle.get("active")
            else "IN_ZONE_PREPARE_ONLY"
            if distance_points == 0
            else "APPROACHING_PREPARE_ONLY"
            if distance_atr <= 0.75 and correct_side
            else "ACTIVE_WATCH_PREPARE_ONLY"
        )
        payloads.append(
            {
                **asdict(zone),
                "available_at": zone.available_at.isoformat(),
                "origin_at": zone.origin_at.isoformat(),
                "departure_at": zone.departure_at.isoformat(),
                "age_hours": round(age_hours, 3),
                "age_bucket": _age_bucket(zone.timeframe, age_hours),
                "age_bars": round(
                    age_hours / (1.0 if zone.timeframe == "H1" else 4.0 if zone.timeframe == "H4" else 24.0),
                    3,
                ),
                "distance_points": round(distance_points, 4),
                "distance_atr": round(distance_atr, 4),
                "correct_side": correct_side,
                "lifecycle": lifecycle,
                "htf_nesting_count": nesting_count,
                "nested_in": list(nested_in),
                "liquidity": liquidity,
                "approach": approach,
                "strategic_alignment": alignment,
                "session_context": _session_bucket_wib(now),
                "research_score": score,
                "status": status,
                "execution_influence": False,
                "execution_authority": False,
            }
        )

    payloads.sort(
        key=lambda item: (
            not bool(dict(item.get("lifecycle") or {}).get("active")),
            not bool(item.get("correct_side")),
            -int(item.get("htf_nesting_count") or 0),
            -float(item.get("research_score") or 0.0),
            float(item.get("distance_atr") or 999.0),
            -TIMEFRAME_PRIORITY.get(str(item.get("timeframe") or ""), 0),
        )
    )
    selected = payloads[:MAX_DISPLAY_ZONES]
    path_map = _build_path_map(
        payloads=payloads,
        levels=levels,
        last_price=last_price,
    )
    nearest_demand = dict(path_map.get("nearest_demand") or {}) or None
    nearest_supply = dict(path_map.get("nearest_supply") or {}) or None

    return {
        "contract": CONTRACT,
        "state": "ATLAS_AVAILABLE" if selected else "NO_ACTIVE_SUPPLY_DEMAND_ZONE",
        "as_of": now.isoformat(),
        "last_closed_m15_price": last_price,
        "strategic_bias": str(strategic_bias or "NEUTRAL").upper(),
        "session_context": _session_bucket_wib(now),
        "execution_influence": False,
        "execution_authority": False,
        "total_detected": len(zones),
        "display_count": len(selected),
        "active_count": sum(1 for z in payloads if dict(z.get("lifecycle") or {}).get("active")),
        "timeframe_imbalance_counts": timeframe_counts,
        "nearest_demand": nearest_demand,
        "nearest_supply": nearest_supply,
        "path_map": path_map,
        "zones": selected,
        "explanation": {
            "purpose": "EARLY_HTF_SUPPLY_DEMAND_PREPARATION_RESEARCH",
            "zone_authority": "STRUCTURAL_H1_OR_BASE_DEPARTURE_IMBALANCE_D1_H4_H1",
            "liquidity_role": "CONFLUENCE_ONLY_NOT_STANDALONE_ZONE_GENERATOR",
            "freshness_model": "TOUCH_COUNT_PLUS_MITIGATION_PLUS_STRUCTURAL_BREAK",
            "geometry": "FULL_BASE_WITH_PROXIMAL_DISTAL_BODY_AWARE_BOUNDARIES",
            "execution_rule": "NO_EXECUTION_AUTHORITY_CANONICAL_AFIC_REMAINS_UNCHANGED",
            "score_note": "RESEARCH_SCORE_IS_RANKING_EVIDENCE_NOT_CALIBRATED_WIN_PROBABILITY",
            "session_note": "WIB_SESSION_BUCKET_IS_RESEARCH_CONTEXT_NOT_A_TRADING_GATE",
            "path_engine": "DEMAND_TO_OPPOSING_SUPPLY_AND_SUPPLY_TO_OPPOSING_DEMAND_WITH_INTERNAL_WAYPOINTS",
        },
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_SUPPLY_DEMAND_V182_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_SUPPLY_DEMAND_V182_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_SUPPLY_DEMAND_V182_SYMBOL_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {}
    error: str | None = None
    raw_count = 0
    raw_m5_count = 0
    try:
        previous_atlas = _latest_worker_details(store, WORKER_NAME)
        previous_projection = dict(
            dict(previous_atlas.get("evaluation") or {}).get("m5_path_projection")
            or {}
        )
        regime = _latest_worker_details(store, "ctrader_xau_htf_strategic_regime_v180")
        regime_eval = dict(regime.get("evaluation") or {})
        strategic_bias = str(
            dict(regime_eval.get("current") or {}).get("strategic_bias")
            or "NEUTRAL"
        ).upper()
        feed.ensure_connected()
        raw = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=now - timedelta(days=LOOKBACK_DAYS),
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
        raw_count = len(raw)
        raw_m5 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=now - timedelta(days=M5_LOOKBACK_DAYS),
                to_time=now,
                count=M5_REQUEST_COUNT,
            )
        )
        raw_m5_count = len(raw_m5)
        payload = evaluate_supply_demand_atlas(
            raw,
            as_of=now,
            strategic_bias=strategic_bias,
        )
        path_map = dict(payload.get("path_map") or {})
        m5_path_projection = evaluate_bidirectional_m5_path(
            raw_m5,
            path_map=path_map,
            as_of=now,
            previous_projection=previous_projection,
        )
        reuse_v200 = evaluate_bidirectional_reuse(m5_path_projection)
        for leg_name in ("current_leg", "next_leg"):
            leg = dict(m5_path_projection.get(leg_name) or {})
            if leg:
                leg["zone_reuse_v200"] = dict(reuse_v200.get(leg_name) or {})
                m5_path_projection[leg_name] = leg
        m5_path_projection["zone_reuse_v200"] = reuse_v200

        current_leg = dict(m5_path_projection.get("current_leg") or {})
        micro_refinement = dict(current_leg.get("micro_refinement") or {})
        payload["micro_refinement"] = micro_refinement
        payload["m5_path_projection"] = m5_path_projection
        payload["zone_reuse_v200"] = reuse_v200
        path_map["micro_refinement"] = micro_refinement
        path_map["m5_path_projection"] = m5_path_projection
        path_map["zone_reuse_v200"] = reuse_v200
        payload["path_map"] = path_map
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "execution_authority": False,
            "live_execution_enabled": False,
            "raw_m15_bars": raw_count,
            "raw_m5_bars": raw_m5_count,
            "evaluation": payload,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_SUPPLY_DEMAND_V182 "
        f"healthy={int(healthy)} state={payload.get('state','ERROR')} "
        f"zones={payload.get('display_count',0)} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

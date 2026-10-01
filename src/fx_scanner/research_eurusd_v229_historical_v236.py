from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import floor, isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_structural_targets_v229 import build_structural_target_plan
from .demo_xau_supply_demand_atlas_v182 import SDZone
from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .models import Bar, ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    OBSERVATION_HOURS,
    _first_invalidation_at,
    _price_index,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "EURUSD_V229_HISTORICAL_EXECUTION_V236_1"
ARTIFACT_CONTRACT = "EURUSD_V229_HISTORICAL_EXECUTION_V236_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "EURUSD"
PIP_SIZE = 0.0001
CHILD_LOT = 0.01
CONTRACT_UNITS_PER_LOT = 100_000.0
CHILD_UNITS = CHILD_LOT * CONTRACT_UNITS_PER_LOT
MAX_CHILDREN = 4
H4_STOP_BUFFER_ATR = 0.15
MIN_TERMINAL_RR = 1.50
SIGNAL_TTL = timedelta(hours=16)
MAX_POSITION_HOLD = timedelta(days=30)

BASE_SPREAD_PIPS = 0.8
BASE_SLIPPAGE_PIPS = 0.2
COMMISSION_PIPS_ROUND_TRIP = 0.2
STRESS_SPREAD_MULTIPLIER = 1.25
STRESS_SLIPPAGE_MULTIPLIER = 1.50
MIN_STOP_PIPS = 2.0

# Exact frozen XAU V225.2 successful-turning-depth q10/q35/q60/q85.
# V236 deliberately uses the XAU prior rather than fitting EURUSD on 2012-2026,
# so the transfer test has no EURUSD full-sample depth leakage.
FROZEN_LADDER_DEPTHS: dict[tuple[str, str], tuple[float, float, float, float]] = {
    ("H4", "LONG"): (
        0.030781527531083486,
        0.11522727272727272,
        0.2863348416289593,
        0.5991592920353982,
    ),
    ("H4", "SHORT"): (
        0.029302325581395353,
        0.10518115942028984,
        0.2700473933649289,
        0.5905825242718447,
    ),
    ("H1", "LONG"): (
        0.03204042956411877,
        0.12157126823793489,
        0.2865045592705167,
        0.6131343283582089,
    ),
    ("H1", "SHORT"): (
        0.032282894736842115,
        0.1227739331026528,
        0.29573883161512027,
        0.6136895161290321,
    ),
    ("M15", "LONG"): (
        0.032289449112978534,
        0.12217854869509866,
        0.28660516605166053,
        0.6022788353863382,
    ),
    ("M15", "SHORT"): (
        0.03189471719245847,
        0.1198502707868748,
        0.2809778597785978,
        0.6070292397660819,
    ),
}

# Frozen XAU V225.2 nested hierarchy priors used by V226.
H1_NESTED_P25 = 0.1705211224175521
H1_NESTED_MEDIAN = 0.3740740740740644
H1_NESTED_P75 = 0.6441281138789966
M15_NESTED_P25 = 0.22012867647070358
M15_NESTED_MEDIAN = 0.4620542672722867
M15_NESTED_P75 = 0.7175662878788179


@dataclass(frozen=True, slots=True)
class PriceArrays:
    timestamps: tuple[pd.Timestamp, ...]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray


def price_arrays(frame: pd.DataFrame) -> PriceArrays:
    return PriceArrays(
        timestamps=tuple(pd.Timestamp(value) for value in frame["timestamp"]),
        opens=frame["open"].to_numpy(dtype=float, copy=False),
        highs=frame["high"].to_numpy(dtype=float, copy=False),
        lows=frame["low"].to_numpy(dtype=float, copy=False),
        closes=frame["close"].to_numpy(dtype=float, copy=False),
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


def _zone_dict(zone: SDZone) -> dict[str, Any]:
    return {
        "zone_id": zone.zone_id,
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "direction": zone.direction,
        "low": float(zone.low),
        "high": float(zone.high),
        "proximal": float(zone.proximal),
        "distal": float(zone.distal),
        "available_at": ensure_utc(zone.available_at).isoformat(),
        "origin_at": ensure_utc(zone.origin_at).isoformat(),
        "departure_at": ensure_utc(zone.departure_at).isoformat(),
        "atr_points": float(zone.atr_points),
        "base_bars": int(zone.base_bars),
        "base_range_atr": float(zone.base_range_atr),
        "departure_range_atr": float(zone.departure_range_atr),
        "departure_body_fraction": float(zone.departure_body_fraction),
        "structural_bos": bool(zone.structural_bos),
        "lifecycle": {"active": True},
        "status": "V236_CAUSAL_ACTIVE",
        "execution_influence": False,
        "execution_authority": False,
    }


def _active_at(
    zone: SDZone,
    *,
    at: datetime,
    invalidated_at: dict[str, datetime | None],
    superseded_at: dict[str, datetime | None],
) -> bool:
    point = ensure_utc(at)
    available = ensure_utc(zone.available_at)
    if available > point:
        return False
    if point > available + timedelta(hours=OBSERVATION_HOURS[zone.timeframe]):
        return False
    invalid = invalidated_at.get(zone.zone_id)
    if invalid is not None and ensure_utc(invalid) <= point:
        return False
    superseded = superseded_at.get(zone.zone_id)
    if superseded is not None and ensure_utc(superseded) <= point:
        return False
    return True


def active_zone_dicts(
    zones: Sequence[SDZone],
    *,
    at: datetime,
    invalidated_at: dict[str, datetime | None],
    superseded_at: dict[str, datetime | None],
) -> list[dict[str, Any]]:
    return [
        _zone_dict(zone)
        for zone in zones
        if _active_at(
            zone,
            at=at,
            invalidated_at=invalidated_at,
            superseded_at=superseded_at,
        )
    ]


def _depth_price(direction: str, low: float, high: float, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    if direction == "LONG":
        return float(high) - d * (float(high) - float(low))
    return float(low) + d * (float(high) - float(low))


def _depth_band(direction: str, low: float, high: float, p1: float, p2: float) -> dict[str, float]:
    a = _depth_price(direction, low, high, p1)
    b = _depth_price(direction, low, high, p2)
    return {"low": min(a, b), "high": max(a, b)}


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        a_low, a_high = float(a["low"]), float(a["high"])
        b_low, b_high = float(b["low"]), float(b["high"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return max(0.0, min(a_high, b_high) - max(a_low, b_low))


def _distance_to_zone(price: float, zone: dict[str, Any]) -> float:
    low = float(zone["low"])
    high = float(zone["high"])
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _select_h1(
    active: Sequence[dict[str, Any]],
    *,
    parent: dict[str, Any],
    hotspot: dict[str, Any],
    direction: str,
    price: float,
) -> dict[str, Any]:
    candidates = [
        dict(zone)
        for zone in active
        if str(zone.get("timeframe") or "").upper() == "H1"
        and str(zone.get("direction") or "").upper() == direction
        and _overlap(parent, zone) > 0.0
    ]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda zone: (
            -int(_overlap(hotspot, zone) > 0.0),
            -_overlap(hotspot, zone),
            _distance_to_zone(price, zone),
            float(zone["high"]) - float(zone["low"]),
            str(zone.get("available_at") or ""),
        )
    )
    return candidates[0]


def _clip_geometry(child: dict[str, float], parent: dict[str, Any]) -> dict[str, float]:
    low = max(float(child["low"]), float(parent["low"]))
    high = min(float(child["high"]), float(parent["high"]))
    return {} if high < low else {"low": low, "high": high}


def _select_m15(
    active: Sequence[dict[str, Any]],
    *,
    parent: dict[str, Any],
    locator: dict[str, Any],
    direction: str,
    price: float,
) -> dict[str, Any]:
    candidates = [
        dict(zone)
        for zone in active
        if str(zone.get("timeframe") or "").upper() == "M15"
        and str(zone.get("direction") or "").upper() == direction
        and _overlap(parent, zone) > 0.0
    ]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda zone: (
            -int(_overlap(locator, zone) > 0.0),
            -_overlap(locator, zone),
            _distance_to_zone(price, zone),
            float(zone["high"]) - float(zone["low"]),
            str(zone.get("available_at") or ""),
        )
    )
    return candidates[0]


def _last_close_at(px: PriceArrays, at: datetime) -> float | None:
    index = bisect_right(px.timestamps, pd.Timestamp(ensure_utc(at))) - 1
    if index < 0:
        return None
    return float(px.closes[index])


def _candidate_geometry(
    *,
    parent: SDZone,
    active: Sequence[dict[str, Any]],
    price: float,
) -> dict[str, Any]:
    direction = str(parent.direction).upper()
    parent_dict = _zone_dict(parent)
    hotspot = _depth_band(
        direction,
        float(parent.low),
        float(parent.high),
        0.0,
        0.10,
    )
    h1 = _select_h1(
        active,
        parent=parent_dict,
        hotspot=hotspot,
        direction=direction,
        price=price,
    )
    h1_nested: dict[str, float] = {}
    if h1:
        raw = _depth_band(
            direction,
            float(h1["low"]),
            float(h1["high"]),
            H1_NESTED_P25,
            H1_NESTED_P75,
        )
        h1_nested = _clip_geometry(raw, parent_dict)

    m15_parent = h1 or parent_dict
    m15_locator = h1_nested or hotspot
    m15 = _select_m15(
        active,
        parent=m15_parent,
        locator=m15_locator,
        direction=direction,
        price=price,
    )
    m15_nested: dict[str, float] = {}
    if m15:
        raw = _depth_band(
            direction,
            float(m15["low"]),
            float(m15["high"]),
            M15_NESTED_P25,
            M15_NESTED_P75,
        )
        m15_nested = _clip_geometry(raw, m15_locator)

    if m15_nested:
        source = "M15"
        geometry = m15_nested
        source_layer = "M15_NESTED_LOCATOR"
    elif h1_nested:
        source = "H1"
        geometry = h1_nested
        source_layer = "H1_NESTED_LOCATOR"
    else:
        source = "H4"
        geometry = hotspot
        source_layer = "H4_HISTORICAL_HOTSPOT"

    low, high = float(geometry["low"]), float(geometry["high"])
    if high <= low:
        return {}

    depths = FROZEN_LADDER_DEPTHS[(source, direction)]
    slots = []
    for slot, depth in enumerate(depths, start=1):
        if slot <= 2:
            stage = "PRE_TOUCH_LIMIT_REFERENCE"
            activation = "FRESH_DEPTH_ENTRY_CANDIDATE"
        elif slot == 3:
            stage = "RESERVE_M5_RECLAIM_MSS_RETEST"
            activation = "M5_RECLAIM_AND_LOCAL_MSS_CONFIRMED"
        else:
            stage = "RESERVE_M5_DISPLACEMENT_RETEST"
            activation = "M5_DISPLACEMENT_CONFIRMED_AND_RETEST_AVAILABLE"
        slots.append(
            {
                "slot": slot,
                "lot": CHILD_LOT,
                "depth": float(depth),
                "reference_price": _depth_price(direction, low, high, depth),
                "stage": stage,
                "activation": activation,
            }
        )
    return {
        "direction": direction,
        "source_profile_timeframe": source,
        "source_layer": source_layer,
        "entry_low": low,
        "entry_high": high,
        "entry_reference": (low + high) / 2.0,
        "h4": parent_dict,
        "h4_hotspot": hotspot,
        "h1": h1,
        "h1_nested": h1_nested,
        "m15": m15,
        "m15_nested": m15_nested,
        "slots": slots,
    }


def _target_for_slot(
    *,
    slot: int,
    direction: str,
    entry: float,
    stop: float,
    active_zones: Sequence[dict[str, Any]],
) -> tuple[float | None, dict[str, Any]]:
    structural = build_structural_target_plan(
        direction=direction,
        entry=float(entry),
        stop=float(stop),
        htf_zones=list(active_zones),
        minimum_rr=MIN_TERMINAL_RR,
    )
    targets = [dict(x) for x in list(structural.get("broker_scaleout_targets") or [])]
    if not targets or not bool(structural.get("terminal_rr_eligible")):
        return None, structural
    if slot == 1:
        chosen = targets[0]
    elif slot == 2 and len(targets) >= 2:
        chosen = targets[1]
    else:
        chosen = targets[-1]
    value = chosen.get("target_price")
    try:
        target = float(value)
    except (TypeError, ValueError):
        return None, structural
    return target if isfinite(target) else None, structural


def _m5_bars(price_m1: pd.DataFrame) -> tuple[Bar, ...]:
    work = price_m1.set_index("timestamp")
    frame = (
        work.resample("5min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )
    return tuple(
        Bar(
            symbol=SYMBOL,
            timeframe="M5",
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


def _micro_order(
    *,
    slot: int,
    direction: str,
    h1_source: dict[str, Any],
    h4_parent: dict[str, Any],
    m5: Sequence[Bar],
    start_at: datetime,
    end_at: datetime,
    spread_pips: float,
) -> tuple[datetime, float, dict[str, Any]] | None:
    if slot not in {3, 4} or not h1_source:
        return None
    timestamps = tuple(pd.Timestamp(ensure_utc(row.timestamp)) for row in m5)
    start_index = max(0, bisect_left(timestamps, pd.Timestamp(ensure_utc(start_at))) - 160)
    first_eval = bisect_left(timestamps, pd.Timestamp(ensure_utc(start_at)))
    last_eval = bisect_right(timestamps, pd.Timestamp(ensure_utc(end_at)))
    half_spread = 0.5 * float(spread_pips) * PIP_SIZE

    path_map = {
        "active_path": {
            "source_zone": dict(h1_source),
            "reaction_direction": direction,
        }
    }
    for index in range(first_eval, last_eval):
        close_at = ensure_utc(m5[index].timestamp) + timedelta(minutes=5)
        if close_at < ensure_utc(start_at) or close_at > ensure_utc(end_at):
            continue
        rows = m5[max(start_index, index - 159): index + 1]
        micro = evaluate_micro_refinement(
            rows,
            path_map=path_map,
            as_of=close_at,
            parent_source_zone=dict(h4_parent),
        )
        if str(micro.get("direction") or "").upper() != direction:
            continue
        if slot == 3:
            if not bool(micro.get("reclaim_confirmed")) or not bool(micro.get("mss_confirmed")):
                continue
            pocket = dict(micro.get("candidate_entry_pocket") or {})
            raw = pocket.get("high" if direction == "LONG" else "low")
        else:
            if not bool(micro.get("displacement_confirmed")):
                continue
            pocket = dict(micro.get("refined_entry_pocket") or {})
            raw = pocket.get("high" if direction == "LONG" else "low")
        try:
            entry = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(entry) or entry <= 0:
            continue
        current = float(m5[index].close)
        valid_side = (
            entry < current + half_spread
            if direction == "LONG"
            else entry > current - half_spread
        )
        if valid_side:
            return close_at, entry, micro
    return None


def _simulate_limit_trade(
    *,
    px: PriceArrays,
    direction: str,
    order_at: datetime,
    expires_at: datetime,
    entry: float,
    stop: float,
    target: float,
    spread_pips: float,
    slippage_pips: float,
    commission_pips: float = COMMISSION_PIPS_ROUND_TRIP,
) -> dict[str, Any]:
    signal = ensure_utc(order_at)
    expiry = ensure_utc(expires_at)
    if expiry <= signal:
        return {"state": "MISSED", "reason": "NO_PENDING_WINDOW"}

    start = bisect_right(px.timestamps, pd.Timestamp(signal))
    end = bisect_right(px.timestamps, pd.Timestamp(expiry))
    if start >= end:
        return {"state": "MISSED", "reason": "NO_M1_AFTER_ORDER"}

    entry_mask = (
        (px.lows[start:end] <= float(entry)) & (px.highs[start:end] >= float(entry))
    )
    hits = np.flatnonzero(entry_mask)
    if len(hits) == 0:
        return {"state": "MISSED", "reason": "LIMIT_NOT_TOUCHED"}
    entry_index = start + int(hits[0])
    entry_at = ensure_utc(px.timestamps[entry_index].to_pydatetime())

    adverse_fill = 0.5 * (float(spread_pips) + float(slippage_pips)) * PIP_SIZE
    fill = float(entry) + adverse_fill if direction == "LONG" else float(entry) - adverse_fill
    risk = fill - float(stop) if direction == "LONG" else float(stop) - fill
    risk_pips = risk / PIP_SIZE
    if risk <= 0 or risk_pips < MIN_STOP_PIPS:
        return {"state": "REJECTED", "reason": "INVALID_STOP_AFTER_COSTS"}

    horizon = entry_at + MAX_POSITION_HOLD
    eval_end = bisect_right(px.timestamps, pd.Timestamp(horizon))
    if eval_end <= entry_index:
        return {"state": "OPEN", "reason": "NO_OUTCOME_HISTORY"}

    half_exit_spread = 0.5 * float(spread_pips) * PIP_SIZE
    future_high = px.highs[entry_index:eval_end]
    future_low = px.lows[entry_index:eval_end]

    if direction == "LONG":
        stop_mask = future_low - half_exit_spread <= float(stop)
        target_mask = future_high - half_exit_spread >= float(target)
    else:
        stop_mask = future_high + half_exit_spread >= float(stop)
        target_mask = future_low + half_exit_spread <= float(target)

    # Target-only on fill bar is unknowable and is not counted.
    raw_target_on_entry = bool(target_mask[0]) if len(target_mask) else False
    if len(target_mask):
        target_mask = target_mask.copy()
        target_mask[0] = False
    events = np.flatnonzero(stop_mask | target_mask)

    if len(events):
        rel = int(events[0])
        absolute = entry_index + rel
        stop_hit = bool(stop_mask[rel])
        target_hit = bool(target_mask[rel])
        ambiguous = bool(stop_hit and (target_hit or (rel == 0 and raw_target_on_entry)))
        if stop_hit:
            exit_price = float(stop)
            reason = "STOP_FIRST_AMBIGUOUS" if ambiguous else "STOP_HIT"
            state = "LOSS"
        else:
            exit_price = float(target)
            reason = "TARGET_HIT"
            state = "WIN"
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        end_index = absolute
    else:
        # Historical V229 has no discretionary time exit. V236 caps at 30 days
        # to keep the research sample finite and marks it as a timed research exit.
        absolute = min(eval_end - 1, len(px.timestamps) - 1)
        if absolute <= entry_index:
            return {"state": "OPEN", "reason": "HISTORY_ENDED_AFTER_FILL"}
        exit_at = ensure_utc(px.timestamps[absolute].to_pydatetime())
        close = float(px.closes[absolute])
        exit_price = (
            close - half_exit_spread if direction == "LONG"
            else close + half_exit_spread
        )
        reason = "V236_MAX_30D_RESEARCH_EXIT"
        end_index = absolute
        state = "WIN" if (
            exit_price > fill if direction == "LONG" else exit_price < fill
        ) else "LOSS"

    gross_price = (
        float(exit_price) - fill
        if direction == "LONG"
        else fill - float(exit_price)
    )
    gross_r = gross_price / risk
    elapsed_days = max(0.0, (exit_at - entry_at).total_seconds() / 86400.0)
    cost_pips = 0.5 * float(slippage_pips) + float(commission_pips)
    cost_r = cost_pips / risk_pips
    net_r = gross_r - cost_r
    net_pnl = net_r * risk * CHILD_UNITS

    sample_high = px.highs[entry_index:end_index + 1]
    sample_low = px.lows[entry_index:end_index + 1]
    if direction == "LONG":
        mfe = max(0.0, float(np.max(sample_high)) - fill) / risk
        mae = max(0.0, fill - float(np.min(sample_low))) / risk
    else:
        mfe = max(0.0, fill - float(np.min(sample_low))) / risk
        mae = max(0.0, float(np.max(sample_high)) - fill) / risk

    return {
        "state": "WIN" if net_r > 0 else "LOSS" if net_r < 0 else "BREAKEVEN",
        "reason": reason,
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "planned_entry": float(entry),
        "fill_price": float(fill),
        "exit_price": float(exit_price),
        "stop": float(stop),
        "target": float(target),
        "risk_pips": float(risk_pips),
        "gross_r": float(gross_r),
        "cost_r": float(cost_r),
        "net_r": float(net_r),
        "net_pnl_usd": float(net_pnl),
        "mae_r": float(mae),
        "mfe_r": float(mfe),
        "ambiguous_bar": bool(reason == "STOP_FIRST_AMBIGUOUS"),
        "spread_pips": float(spread_pips),
        "slippage_pips": float(slippage_pips),
        "elapsed_days": float(elapsed_days),
    }


def build_year_lifecycle(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> tuple[
    tuple[SDZone, ...],
    tuple[Any, ...],
    dict[str, datetime | None],
    dict[str, datetime | None],
]:
    zones = build_zones(price_m1)
    index = _price_index(price_m1)
    superseded = causal_superseded_at(zones)
    invalidated = {
        zone.zone_id: _first_invalidation_at(
            price_m1,
            zone=zone,
            index=index,
            valid_until=superseded.get(zone.zone_id),
        )
        for zone in zones
    }
    parents = []
    for zone in zones:
        if zone.timeframe != "H4":
            continue
        episode = evaluate_first_touch(
            price_m1,
            zone=zone,
            index=index,
            valid_until=superseded.get(zone.zone_id),
        )
        if episode is None or ensure_utc(episode.touch_at).year != int(target_year):
            continue
        parents.append(episode)
    parents.sort(key=lambda row: (row.touch_at, row.zone_id))
    return zones, tuple(parents), invalidated, superseded


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> dict[str, Any]:
    zones, parent_episodes, invalidated, superseded = build_year_lifecycle(
        price_m1,
        target_year=target_year,
    )
    zone_by_id = {zone.zone_id: zone for zone in zones}
    px = price_arrays(price_m1)
    m5 = _m5_bars(price_m1)

    plans: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    skips: dict[str, int] = {}

    def skip(reason: str) -> None:
        skips[reason] = skips.get(reason, 0) + 1

    for episode in parent_episodes:
        parent = zone_by_id.get(episode.zone_id)
        if parent is None:
            skip("PARENT_NOT_FOUND")
            continue
        direction = str(parent.direction).upper()
        as_of = ensure_utc(episode.touch_at) - timedelta(minutes=1)
        price = _last_close_at(px, as_of)
        if price is None:
            skip("NO_PRETOUCH_PRICE")
            continue
        active = active_zone_dicts(
            zones,
            at=as_of,
            invalidated_at=invalidated,
            superseded_at=superseded,
        )
        geometry = _candidate_geometry(
            parent=parent,
            active=active,
            price=price,
        )
        if not geometry:
            skip("NO_CANDIDATE_GEOMETRY")
            continue
        if direction == "LONG" and price <= float(geometry["entry_high"]):
            skip("NOT_AHEAD_LONG")
            continue
        if direction == "SHORT" and price >= float(geometry["entry_low"]):
            skip("NOT_AHEAD_SHORT")
            continue

        stop = (
            float(parent.low) - H4_STOP_BUFFER_ATR * float(parent.atr_points)
            if direction == "LONG"
            else float(parent.high) + H4_STOP_BUFFER_ATR * float(parent.atr_points)
        )
        plan_at = as_of
        signal_expires = plan_at + SIGNAL_TTL
        active_plan = active_zone_dicts(
            zones,
            at=plan_at,
            invalidated_at=invalidated,
            superseded_at=superseded,
        )

        child_blueprints: list[dict[str, Any]] = []
        enabled = 0
        for slot_row in geometry["slots"]:
            slot = int(slot_row["slot"])
            reference = float(slot_row["reference_price"])
            target, structural = _target_for_slot(
                slot=slot,
                direction=direction,
                entry=reference,
                stop=stop,
                active_zones=active_plan,
            )
            if target is not None:
                enabled += 1
            child_blueprints.append(
                {
                    **slot_row,
                    "planned_target": target,
                    "terminal_rr_eligible": bool(structural.get("terminal_rr_eligible")),
                    "mapped_target_count": len(list(structural.get("mapped_targets") or [])),
                }
            )
        if enabled == 0:
            skip("NO_STRUCTURAL_TARGET")
            continue

        plan_id = f"V236:{target_year}:{parent.zone_id}"
        plan = {
            "plan_id": plan_id,
            "year": int(target_year),
            "direction": direction,
            "plan_at": plan_at.isoformat(),
            "signal_expires_at": signal_expires.isoformat(),
            "parent_touch_at": ensure_utc(episode.touch_at).isoformat(),
            "h4_zone_id": parent.zone_id,
            "candidate_source": geometry["source_profile_timeframe"],
            "source_layer": geometry["source_layer"],
            "entry_low": float(geometry["entry_low"]),
            "entry_high": float(geometry["entry_high"]),
            "stop": float(stop),
            "h1_zone_id": None if not geometry["h1"] else geometry["h1"].get("zone_id"),
            "m15_zone_id": None if not geometry["m15"] else geometry["m15"].get("zone_id"),
            "children": child_blueprints,
        }
        plans.append(plan)

        for cost_mode, spread_pips, slippage_pips in (
            ("BASE", BASE_SPREAD_PIPS, BASE_SLIPPAGE_PIPS),
            (
                "STRESS",
                BASE_SPREAD_PIPS * STRESS_SPREAD_MULTIPLIER,
                BASE_SLIPPAGE_PIPS * STRESS_SLIPPAGE_MULTIPLIER,
            ),
        ):
            for child in child_blueprints:
                slot = int(child["slot"])
                if slot <= 2:
                    order_at = plan_at
                    entry = float(child["reference_price"])
                    target = child.get("planned_target")
                    activation = "PRE_TOUCH_LIMIT"
                    micro_state = None
                else:
                    micro_order = _micro_order(
                        slot=slot,
                        direction=direction,
                        h1_source=dict(geometry["h1"] or {}),
                        h4_parent=_zone_dict(parent),
                        m5=m5,
                        start_at=ensure_utc(episode.touch_at),
                        end_at=signal_expires,
                        spread_pips=spread_pips,
                    )
                    if micro_order is None:
                        trades.append(
                            {
                                "plan_id": plan_id,
                                "year": int(target_year),
                                "cost_mode": cost_mode,
                                "slot": slot,
                                "direction": direction,
                                "state": "MISSED",
                                "reason": "NO_M5_ACTIVATION",
                                "plan_at": plan_at.isoformat(),
                                "signal_expires_at": signal_expires.isoformat(),
                            }
                        )
                        continue
                    order_at, entry, micro = micro_order
                    active_micro = active_zone_dicts(
                        zones,
                        at=order_at,
                        invalidated_at=invalidated,
                        superseded_at=superseded,
                    )
                    target, structural = _target_for_slot(
                        slot=slot,
                        direction=direction,
                        entry=entry,
                        stop=stop,
                        active_zones=active_micro,
                    )
                    activation = (
                        "M5_RECLAIM_MSS_RETEST"
                        if slot == 3
                        else "M5_DISPLACEMENT_RETEST"
                    )
                    micro_state = str(micro.get("state") or "")
                    if target is None or not bool(structural.get("terminal_rr_eligible")):
                        trades.append(
                            {
                                "plan_id": plan_id,
                                "year": int(target_year),
                                "cost_mode": cost_mode,
                                "slot": slot,
                                "direction": direction,
                                "state": "REJECTED",
                                "reason": "NO_VALID_STRUCTURAL_TP_AT_ACTIVATION",
                                "plan_at": plan_at.isoformat(),
                                "signal_expires_at": signal_expires.isoformat(),
                                "order_at": order_at.isoformat(),
                            }
                        )
                        continue

                if target is None:
                    trades.append(
                        {
                            "plan_id": plan_id,
                            "year": int(target_year),
                            "cost_mode": cost_mode,
                            "slot": slot,
                            "direction": direction,
                            "state": "REJECTED",
                            "reason": "NO_VALID_STRUCTURAL_TP",
                            "plan_at": plan_at.isoformat(),
                            "signal_expires_at": signal_expires.isoformat(),
                            "order_at": order_at.isoformat(),
                        }
                    )
                    continue
                result = _simulate_limit_trade(
                    px=px,
                    direction=direction,
                    order_at=order_at,
                    expires_at=signal_expires,
                    entry=float(entry),
                    stop=float(stop),
                    target=float(target),
                    spread_pips=float(spread_pips),
                    slippage_pips=float(slippage_pips),
                    commission_pips=float(COMMISSION_PIPS_ROUND_TRIP),
                )
                trades.append(
                    {
                        "plan_id": plan_id,
                        "year": int(target_year),
                        "cost_mode": cost_mode,
                        "slot": slot,
                        "direction": direction,
                        "activation": activation,
                        "micro_state": micro_state,
                        "candidate_source": geometry["source_profile_timeframe"],
                        "source_layer": geometry["source_layer"],
                        "h4_zone_id": parent.zone_id,
                        "h1_zone_id": None if not geometry["h1"] else geometry["h1"].get("zone_id"),
                        "m15_zone_id": None if not geometry["m15"] else geometry["m15"].get("zone_id"),
                        "plan_at": plan_at.isoformat(),
                        "signal_expires_at": signal_expires.isoformat(),
                        "order_at": ensure_utc(order_at).isoformat(),
                        **result,
                    }
                )

    return {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_YEAR_SHARD_1",
        "research_version": RESEARCH_VERSION,
        "pair": SYMBOL,
        "year": int(target_year),
        "parent_h4_first_touch_count": len(parent_episodes),
        "plan_count": len(plans),
        "trade_record_count": len(trades),
        "plans": plans,
        "trades": trades,
        "skips": skips,
        "cost_contract": {
            "base_spread_pips": BASE_SPREAD_PIPS,
            "base_slippage_pips": BASE_SLIPPAGE_PIPS,
            "commission_pips_round_trip": COMMISSION_PIPS_ROUND_TRIP,
            "stress_spread_multiplier": STRESS_SPREAD_MULTIPLIER,
            "stress_slippage_multiplier": STRESS_SLIPPAGE_MULTIPLIER,
            "ambiguous_bar_policy": "STOP_FIRST",
        },
        "execution_contract": {
            "child_lot": CHILD_LOT,
            "max_children": MAX_CHILDREN,
            "pretouch_slots": [1, 2],
            "m5_confirmation_slots": [3, 4],
            "signal_ttl_hours": SIGNAL_TTL.total_seconds() / 3600.0,
            "terminal_rr_min": MIN_TERMINAL_RR,
            "max_position_research_hold_days": MAX_POSITION_HOLD.total_seconds() / 86400.0,
            "frozen_prior": "XAU_V225_2",
            "eurusd_full_sample_calibration_used": False,
        },
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }


def effective_trades(
    plans: Sequence[dict[str, Any]],
    trades: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, datetime]]:
    ordered_plans = sorted(
        (dict(row) for row in plans),
        key=lambda row: (_dt(row.get("plan_at")) or datetime.max.replace(tzinfo=UTC), str(row.get("plan_id"))),
    )
    cancel_at: dict[str, datetime] = {}
    for index, plan in enumerate(ordered_plans):
        expiry = _dt(plan.get("signal_expires_at"))
        if expiry is None:
            continue
        next_plan = (
            _dt(ordered_plans[index + 1].get("plan_at"))
            if index + 1 < len(ordered_plans)
            else None
        )
        cancel_at[str(plan.get("plan_id"))] = (
            expiry if next_plan is None else min(expiry, next_plan)
        )

    output: list[dict[str, Any]] = []
    for raw in trades:
        row = dict(raw)
        if str(row.get("state") or "") not in {"WIN", "LOSS", "BREAKEVEN"}:
            output.append(row)
            continue
        entry_at = _dt(row.get("entry_at"))
        cutoff = cancel_at.get(str(row.get("plan_id") or ""))
        if entry_at is not None and cutoff is not None and entry_at >= cutoff:
            output.append(
                {
                    **row,
                    "state": "CANCELLED",
                    "reason": "PARENT_SUPERSEDED_OR_EXPIRED_BEFORE_FILL",
                    "original_state": row.get("state"),
                }
            )
        else:
            output.append(row)
    return output, cancel_at


def summarize_trades(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    ]
    wins = [row for row in completed if float(row.get("net_r") or 0.0) > 0]
    losses = [row for row in completed if float(row.get("net_r") or 0.0) < 0]
    gross_profit = sum(float(row.get("net_r") or 0.0) for row in wins)
    gross_loss = -sum(float(row.get("net_r") or 0.0) for row in losses)
    pnls = [float(row.get("net_pnl_usd") or 0.0) for row in completed]
    rs = [float(row.get("net_r") or 0.0) for row in completed]
    return {
        "completed": len(completed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(completed) - len(wins) - len(losses),
        "win_rate": None if not completed else len(wins) / len(completed),
        "profit_factor_r": None if gross_loss <= 0 else gross_profit / gross_loss,
        "expectancy_r": None if not rs else float(np.mean(np.array(rs, dtype=float))),
        "median_r": None if not rs else float(np.median(np.array(rs, dtype=float))),
        "net_pnl_usd_fixed_001": float(sum(pnls)),
        "mae_r_median": (
            None
            if not completed
            else float(np.median(np.array([float(row.get("mae_r") or 0.0) for row in completed])))
        ),
        "mfe_r_median": (
            None
            if not completed
            else float(np.median(np.array([float(row.get("mfe_r") or 0.0) for row in completed])))
        ),
        "ambiguous_stop_first": sum(bool(row.get("ambiguous_bar")) for row in completed),
        "missed": sum(str(row.get("state") or "") == "MISSED" for row in rows),
        "rejected": sum(str(row.get("state") or "") == "REJECTED" for row in rows),
        "cancelled": sum(str(row.get("state") or "") == "CANCELLED" for row in rows),
    }


def account_ledger(
    rows: Sequence[dict[str, Any]],
    *,
    initial_balance: float = 100.0,
    leverage: float = 100.0,
    margin_cap_fraction: float | None = None,
) -> dict[str, Any]:
    candidates = [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
        and _dt(row.get("entry_at")) is not None
        and _dt(row.get("exit_at")) is not None
    ]
    candidates.sort(
        key=lambda row: (
            _dt(row.get("entry_at")) or datetime.max.replace(tzinfo=UTC),
            int(row.get("slot") or 0),
            str(row.get("plan_id") or ""),
        )
    )

    balance = float(initial_balance)
    peak = balance
    max_dd = 0.0
    used_margin = 0.0
    max_used_margin = 0.0
    max_margin_fraction = 0.0
    accepted: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    margin_rejected = 0
    bust = False
    realized_curve = [{"at": None, "balance": balance}]

    def release_until(point: datetime) -> None:
        nonlocal balance, peak, max_dd, used_margin, open_rows, bust
        closing = sorted(
            [
                row
                for row in open_rows
                if (_dt(row.get("exit_at")) or datetime.max.replace(tzinfo=UTC)) <= point
            ],
            key=lambda row: _dt(row.get("exit_at")) or datetime.max.replace(tzinfo=UTC),
        )
        for row in closing:
            pnl = float(row.get("net_pnl_usd") or 0.0)
            balance = max(0.0, balance + pnl)
            used_margin = max(0.0, used_margin - float(row.get("_margin_required") or 0.0))
            peak = max(peak, balance)
            dd = 0.0 if peak <= 0 else (peak - balance) / peak
            max_dd = max(max_dd, dd)
            realized_curve.append(
                {"at": row.get("exit_at"), "balance": balance}
            )
            if balance <= 0:
                bust = True
        closed_ids = {id(row) for row in closing}
        open_rows = [row for row in open_rows if id(row) not in closed_ids]

    for row in candidates:
        entry_at = _dt(row.get("entry_at"))
        assert entry_at is not None
        release_until(entry_at)
        if bust or balance <= 0:
            break
        fill = float(row.get("fill_price") or row.get("planned_entry") or 0.0)
        if fill <= 0:
            continue
        margin = CHILD_UNITS * fill / float(leverage)
        projected = used_margin + margin
        cap = balance if margin_cap_fraction is None else balance * float(margin_cap_fraction)
        if projected > cap + 1e-12:
            margin_rejected += 1
            continue
        row["_margin_required"] = margin
        accepted.append(row)
        open_rows.append(row)
        used_margin = projected
        max_used_margin = max(max_used_margin, used_margin)
        if balance > 0:
            max_margin_fraction = max(max_margin_fraction, used_margin / balance)

    release_until(datetime.max.replace(tzinfo=UTC))
    accepted_summary = summarize_trades(accepted)
    return {
        "initial_balance": float(initial_balance),
        "leverage": float(leverage),
        "child_lot": CHILD_LOT,
        "margin_cap_fraction": margin_cap_fraction,
        "accepted_trades": len(accepted),
        "margin_rejected": int(margin_rejected),
        "ending_balance": float(balance),
        "net_profit": float(balance - initial_balance),
        "return_multiple": float(balance / initial_balance) if initial_balance > 0 else None,
        "realized_max_drawdown_pct": float(max_dd * 100.0),
        "max_used_margin_usd": float(max_used_margin),
        "max_used_margin_fraction_of_balance": float(max_margin_fraction),
        "account_bust": bool(bust),
        "trade_summary": accepted_summary,
        "realized_curve": realized_curve,
    }

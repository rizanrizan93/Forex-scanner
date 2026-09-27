from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_structural_targets_v229 import build_structural_target_plan
from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .models import Bar, ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    OBSERVATION_HOURS,
    PriceIndex,
    _first_invalidation_at,
    _load_price_frame,
    _price_index,
    _resample_ohlc,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "EURUSD_V229_EXECUTION_BACKTEST_V236_1"
ARTIFACT_CONTRACT = "EURUSD_V229_EXECUTION_BACKTEST_V236_1_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
LIVE_EXECUTION_ENABLED = False

SYMBOL = "EURUSD"
PIP_SIZE = 0.0001
CHILD_LOT = 0.01
CHILD_UNITS = 1000.0
MAX_CHILDREN = 4
MIN_TERMINAL_RR = 1.50
H4_STOP_BUFFER_ATR = 0.15
PARENT_TTL_HOURS = 16.0
HEALTHY_ARM_DISTANCE_ATR = 1.0

BASE_SPREAD_PIPS = 0.8
BASE_SLIPPAGE_PIPS = 0.2
BASE_COMMISSION_PIPS_ROUND_TRIP = 0.2

CURRENT_PRIOR = {
    "H4": {
        "LONG": (0.026576, 0.093014, 0.228222, 0.516910),
        "SHORT": (0.027085, 0.094796, 0.259630, 0.574505),
    },
    "H1": {
        "LONG": (0.030172, 0.110230, 0.267870, 0.578621),
        "SHORT": (0.031050, 0.115596, 0.281023, 0.595601),
    },
    "M15": {
        "LONG": (0.030169, 0.110524, 0.275162, 0.589103),
        "SHORT": (0.031056, 0.115306, 0.275069, 0.593569),
    },
}
CURRENT_HIERARCHY = {
    "h1": (0.14621409921674045, 0.36249999999997573, 0.6147540983606796),
    "m15": (0.2371553884711091, 0.4888668975755126, 0.7336134453782902),
}

SEED_2012_2018_PRIOR = {
    "H4": {
        "LONG": (0.025986, 0.090952, 0.244138, 0.533488),
        "SHORT": (0.027267, 0.095433, 0.261136, 0.595750),
    },
    "H1": {
        "LONG": (0.030106, 0.109795, 0.269051, 0.576551),
        "SHORT": (0.032081, 0.120226, 0.286335, 0.604441),
    },
    "M15": {
        "LONG": (0.030701, 0.114116, 0.280000, 0.592630),
        "SHORT": (0.032373, 0.122413, 0.284064, 0.607564),
    },
}
SEED_2012_2018_HIERARCHY = {
    "h1": (0.14285714285714285, 0.36320754716986564, 0.6225165562914482),
    "m15": (0.24962654296719425, 0.4866102889359094, 0.7277081922815489),
}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone_dict(zone: Any) -> dict[str, Any]:
    raw = asdict(zone)
    for key in ("available_at", "origin_at", "departure_at"):
        value = raw.get(key)
        if isinstance(value, datetime):
            raw[key] = ensure_utc(value).isoformat()
    return raw


def _zone_active_at(
    zone: Any,
    at: datetime,
    *,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> bool:
    point = ensure_utc(at)
    available = ensure_utc(zone.available_at)
    if available > point:
        return False
    max_hours = float(OBSERVATION_HOURS.get(zone.timeframe, 24 * 30))
    if point > available + timedelta(hours=max_hours):
        return False
    replace = superseded.get(zone.zone_id)
    if replace is not None and ensure_utc(replace) <= point:
        return False
    invalid = invalidated.get(zone.zone_id)
    return invalid is None or ensure_utc(invalid) > point


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> float:
    return max(0.0, min(float(a_high), float(b_high)) - max(float(a_low), float(b_low)))


def _distance(price: float, low: float, high: float) -> float:
    if price < low:
        return low - price
    if price > high:
        return price - high
    return 0.0


def _price_at_depth(zone: Any, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    width = float(zone.high) - float(zone.low)
    if zone.direction == "LONG":
        return float(zone.high) - d * width
    return float(zone.low) + d * width


def _depth_interval(zone: Any, lower: float, upper: float) -> tuple[float, float]:
    a = _price_at_depth(zone, lower)
    b = _price_at_depth(zone, upper)
    return min(a, b), max(a, b)


def _clip(interval: tuple[float, float], parent: tuple[float, float]) -> tuple[float, float] | None:
    low = max(float(interval[0]), float(parent[0]))
    high = min(float(interval[1]), float(parent[1]))
    return None if high <= low else (low, high)


def _bars_from_frame(frame: pd.DataFrame, timeframe: str) -> tuple[Bar, ...]:
    out: list[Bar] = []
    for _, row in frame.iterrows():
        out.append(
            Bar(
                symbol=SYMBOL,
                timeframe=timeframe,
                timestamp=ensure_utc(pd.Timestamp(row["time"]).to_pydatetime()),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                tick_count=1,
                spread_avg=0.0,
                spread_max=0.0,
            )
        )
    return tuple(out)


def _select_h1(
    zones: Sequence[Any],
    *,
    parent: Any,
    hotspot: tuple[float, float],
    direction: str,
    price: float,
    at: datetime,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> Any | None:
    candidates = []
    for zone in zones:
        if zone.timeframe != "H1" or zone.direction != direction:
            continue
        if not _zone_active_at(zone, at, superseded=superseded, invalidated=invalidated):
            continue
        if _overlap(parent.low, parent.high, zone.low, zone.high) <= 0:
            continue
        hot_overlap = _overlap(hotspot[0], hotspot[1], zone.low, zone.high)
        candidates.append(
            (
                -int(hot_overlap > 0),
                -hot_overlap,
                _distance(price, float(zone.low), float(zone.high)),
                float(zone.high) - float(zone.low),
                -ensure_utc(zone.available_at).timestamp(),
                zone,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[:-1])
    return candidates[0][-1]


def _select_m15(
    zones: Sequence[Any],
    *,
    parent: Any,
    locator: tuple[float, float],
    direction: str,
    price: float,
    at: datetime,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> Any | None:
    candidates = []
    for zone in zones:
        if zone.timeframe != "M15" or zone.direction != direction:
            continue
        if not _zone_active_at(zone, at, superseded=superseded, invalidated=invalidated):
            continue
        if _overlap(parent.low, parent.high, zone.low, zone.high) <= 0:
            continue
        locator_overlap = _overlap(locator[0], locator[1], zone.low, zone.high)
        candidates.append(
            (
                -int(locator_overlap > 0),
                -locator_overlap,
                _distance(price, float(zone.low), float(zone.high)),
                float(zone.high) - float(zone.low),
                -ensure_utc(zone.available_at).timestamp(),
                zone,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[:-1])
    return candidates[0][-1]


def _candidate_geometry(
    *,
    h4: Any,
    zones: Sequence[Any],
    direction: str,
    price: float,
    at: datetime,
    hierarchy: dict[str, tuple[float, float, float]],
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> tuple[tuple[float, float], str, Any | None, Any | None]:
    h4_hotspot = _depth_interval(h4, 0.0, 0.10)
    h1 = _select_h1(
        zones,
        parent=h4,
        hotspot=h4_hotspot,
        direction=direction,
        price=price,
        at=at,
        superseded=superseded,
        invalidated=invalidated,
    )
    if h1 is None:
        return h4_hotspot, "H4_HISTORICAL_HOTSPOT", None, None

    h1_q = hierarchy["h1"]
    h1_locator = _clip(
        _depth_interval(h1, h1_q[0], h1_q[2]),
        (float(h4.low), float(h4.high)),
    )
    if h1_locator is None:
        h1_locator = h4_hotspot

    m15 = _select_m15(
        zones,
        parent=h1,
        locator=h1_locator,
        direction=direction,
        price=price,
        at=at,
        superseded=superseded,
        invalidated=invalidated,
    )
    if m15 is None:
        return h1_locator, "H1_NESTED_LOCATOR", h1, None

    m15_q = hierarchy["m15"]
    m15_locator = _clip(
        _depth_interval(m15, m15_q[0], m15_q[2]),
        h1_locator,
    )
    if m15_locator is None:
        return h1_locator, "H1_NESTED_LOCATOR", h1, m15
    return m15_locator, "M15_NESTED_LOCATOR", h1, m15


def _source_tf(source_layer: str) -> str:
    if source_layer.startswith("M15"):
        return "M15"
    if source_layer.startswith("H1"):
        return "H1"
    return "H4"


def _ladder_prices(
    *,
    geometry: tuple[float, float],
    direction: str,
    source_tf: str,
    prior: dict[str, dict[str, tuple[float, float, float, float]]],
) -> list[float]:
    low, high = geometry
    width = high - low
    depths = prior[source_tf][direction]
    prices = []
    for depth in depths:
        if direction == "LONG":
            price = high - float(depth) * width
        else:
            price = low + float(depth) * width
        prices.append(float(price))
    return prices


def _approach_ok(zone: Any, price: float) -> bool:
    if zone.direction == "LONG":
        return float(price) > float(zone.high)
    return float(price) < float(zone.low)


def _first_plan_time(
    *,
    zone: Any,
    touch_at: datetime,
    m15: pd.DataFrame,
    arm_mode: str,
) -> tuple[datetime, float] | None:
    available = ensure_utc(zone.available_at)
    rows = m15[
        (m15["time"] + pd.Timedelta(minutes=15) >= pd.Timestamp(available))
        & (m15["time"] + pd.Timedelta(minutes=15) < pd.Timestamp(touch_at))
    ]
    if rows.empty:
        return None
    for _, row in rows.iterrows():
        at = ensure_utc((pd.Timestamp(row["time"]) + pd.Timedelta(minutes=15)).to_pydatetime())
        price = float(row["close"])
        if not _approach_ok(zone, price):
            continue
        if arm_mode == "HEALTHY_1ATR":
            dist = _distance(price, float(zone.low), float(zone.high))
            if dist > float(zone.atr_points) * HEALTHY_ARM_DISTANCE_ATR:
                continue
        return at, price
    return None


def _active_target_zones(
    zones: Sequence[Any],
    *,
    at: datetime,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    m15: list[dict[str, Any]] = []
    htf: list[dict[str, Any]] = []
    for zone in zones:
        if zone.timeframe not in {"M15", "H1", "H4"}:
            continue
        if not _zone_active_at(zone, at, superseded=superseded, invalidated=invalidated):
            continue
        raw = _zone_dict(zone)
        if zone.timeframe == "M15":
            m15.append(raw)
        else:
            htf.append(raw)
    return m15, htf


def _target_for_slot(
    *,
    slot: int,
    direction: str,
    entry: float,
    stop: float,
    zones: Sequence[Any],
    at: datetime,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> tuple[float | None, dict[str, Any]]:
    m15, htf = _active_target_zones(
        zones,
        at=at,
        superseded=superseded,
        invalidated=invalidated,
    )
    structural = build_structural_target_plan(
        direction=direction,
        entry=float(entry),
        stop=float(stop),
        m15_zones=m15,
        htf_zones=htf,
        minimum_rr=MIN_TERMINAL_RR,
    )
    targets = [dict(row) for row in list(structural.get("broker_scaleout_targets") or [])]
    if not targets or not bool(structural.get("terminal_rr_eligible")):
        return None, structural
    if slot == 1:
        chosen = targets[0]
    elif slot == 2 and len(targets) >= 2:
        chosen = targets[1]
    else:
        chosen = targets[-1]
    return _f(chosen.get("target_price")), structural


def _parent_plans(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
    prior: dict[str, dict[str, tuple[float, float, float, float]]],
    hierarchy: dict[str, tuple[float, float, float]],
    arm_mode: str,
) -> tuple[list[dict[str, Any]], tuple[Any, ...], dict[str, datetime | None], dict[str, datetime | None]]:
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
    m15 = _resample_ohlc(price_m1, "15min")
    plans: list[dict[str, Any]] = []

    for h4 in zones:
        if h4.timeframe != "H4":
            continue
        episode = evaluate_first_touch(
            price_m1,
            zone=h4,
            index=index,
            valid_until=superseded.get(h4.zone_id),
        )
        if episode is None or ensure_utc(episode.touch_at).year != int(target_year):
            continue
        plan_point = _first_plan_time(
            zone=h4,
            touch_at=episode.touch_at,
            m15=m15,
            arm_mode=arm_mode,
        )
        if plan_point is None:
            continue
        plan_at, reference_price = plan_point
        if not _zone_active_at(
            h4,
            plan_at,
            superseded=superseded,
            invalidated=invalidated,
        ):
            continue

        geometry, source_layer, h1, m15_child = _candidate_geometry(
            h4=h4,
            zones=zones,
            direction=h4.direction,
            price=reference_price,
            at=plan_at,
            hierarchy=hierarchy,
            superseded=superseded,
            invalidated=invalidated,
        )
        if geometry[1] <= geometry[0]:
            continue
        ladder = _ladder_prices(
            geometry=geometry,
            direction=h4.direction,
            source_tf=_source_tf(source_layer),
            prior=prior,
        )
        stop = (
            float(h4.low) - H4_STOP_BUFFER_ATR * float(h4.atr_points)
            if h4.direction == "LONG"
            else float(h4.high) + H4_STOP_BUFFER_ATR * float(h4.atr_points)
        )
        if h4.direction == "LONG" and stop >= geometry[0]:
            continue
        if h4.direction == "SHORT" and stop <= geometry[1]:
            continue
        expires = plan_at + timedelta(hours=PARENT_TTL_HOURS)
        replace = superseded.get(h4.zone_id)
        invalid = invalidated.get(h4.zone_id)
        for boundary in (replace, invalid):
            if boundary is not None and ensure_utc(boundary) < expires:
                expires = ensure_utc(boundary)
        if expires <= plan_at:
            continue

        children: list[dict[str, Any]] = []
        for slot, entry in enumerate(ladder, start=1):
            target = None
            structural: dict[str, Any] = {}
            if slot <= 2:
                target, structural = _target_for_slot(
                    slot=slot,
                    direction=h4.direction,
                    entry=entry,
                    stop=stop,
                    zones=zones,
                    at=plan_at,
                    superseded=superseded,
                    invalidated=invalidated,
                )
            children.append(
                {
                    "slot": slot,
                    "reference_entry": entry,
                    "planned_target": target,
                    "terminal_rr_eligible": bool(structural.get("terminal_rr_eligible")) if structural else False,
                }
            )
        if not any(row.get("planned_target") is not None for row in children[:2]):
            continue

        plans.append(
            {
                "parent_id": h4.zone_id,
                "direction": h4.direction,
                "plan_at": plan_at,
                "natural_expires_at": expires,
                "touch_at": ensure_utc(episode.touch_at),
                "reference_price": reference_price,
                "candidate_low": float(geometry[0]),
                "candidate_high": float(geometry[1]),
                "source_layer": source_layer,
                "h4": h4,
                "h1": h1,
                "m15": m15_child,
                "stop": float(stop),
                "children": children,
            }
        )

    plans.sort(key=lambda row: (row["plan_at"], row["parent_id"]))
    for i, plan in enumerate(plans):
        next_plan_at = plans[i + 1]["plan_at"] if i + 1 < len(plans) else None
        cancel_at = plan["natural_expires_at"]
        if next_plan_at is not None and next_plan_at < cancel_at:
            cancel_at = next_plan_at
        plan["cancel_at"] = cancel_at
    return plans, zones, superseded, invalidated


def _m5_submission_orders(
    *,
    plan: dict[str, Any],
    m5_bars: Sequence[Bar],
    zones: Sequence[Any],
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
) -> list[dict[str, Any]]:
    h1 = plan.get("h1")
    if h1 is None:
        return []
    source = _zone_dict(h1)
    parent = _zone_dict(plan["h4"])
    direction = str(plan["direction"])
    plan_at = ensure_utc(plan["plan_at"])
    cancel_at = ensure_utc(plan["cancel_at"])
    out: list[dict[str, Any]] = []
    done: set[int] = set()

    for i, bar in enumerate(m5_bars):
        close_at = ensure_utc(bar.timestamp) + timedelta(minutes=5)
        if close_at < plan_at:
            continue
        if close_at >= cancel_at:
            break
        if len(done) == 2:
            break
        window = tuple(m5_bars[max(0, i - 180): i + 1])
        micro = evaluate_micro_refinement(
            window,
            path_map={
                "active_path": {
                    "source_zone": source,
                    "reaction_direction": direction,
                }
            },
            as_of=close_at,
            parent_source_zone=parent,
        )
        last_price = float(bar.close)

        if 3 not in done and bool(micro.get("reclaim_confirmed")) and bool(micro.get("mss_confirmed")):
            pocket = dict(micro.get("candidate_entry_pocket") or {})
            entry = _f(pocket.get("high" if direction == "LONG" else "low"))
            if entry is not None:
                side_valid = entry < last_price if direction == "LONG" else entry > last_price
                if side_valid:
                    target, structural = _target_for_slot(
                        slot=3,
                        direction=direction,
                        entry=entry,
                        stop=float(plan["stop"]),
                        zones=zones,
                        at=close_at,
                        superseded=superseded,
                        invalidated=invalidated,
                    )
                    if target is not None and bool(structural.get("terminal_rr_eligible")):
                        out.append(
                            {
                                "slot": 3,
                                "submit_at": close_at,
                                "entry": float(entry),
                                "target": float(target),
                                "activation": "M5_RECLAIM_MSS_RETEST",
                            }
                        )
                        done.add(3)

        if 4 not in done and bool(micro.get("displacement_confirmed")):
            pocket = dict(micro.get("refined_entry_pocket") or {})
            entry = _f(pocket.get("high" if direction == "LONG" else "low"))
            if entry is not None:
                side_valid = entry < last_price if direction == "LONG" else entry > last_price
                if side_valid:
                    target, structural = _target_for_slot(
                        slot=4,
                        direction=direction,
                        entry=entry,
                        stop=float(plan["stop"]),
                        zones=zones,
                        at=close_at,
                        superseded=superseded,
                        invalidated=invalidated,
                    )
                    if target is not None and bool(structural.get("terminal_rr_eligible")):
                        out.append(
                            {
                                "slot": 4,
                                "submit_at": close_at,
                                "entry": float(entry),
                                "target": float(target),
                                "activation": "M5_DISPLACEMENT_RETEST",
                            }
                        )
                        done.add(4)
    return out


def _simulate_child(
    price_m1: pd.DataFrame,
    *,
    index: PriceIndex,
    parent_id: str,
    slot: int,
    direction: str,
    submit_at: datetime,
    cancel_at: datetime,
    entry: float,
    stop: float,
    target: float,
    activation: str,
    spread_pips: float = BASE_SPREAD_PIPS,
    slippage_pips: float = BASE_SLIPPAGE_PIPS,
    commission_pips: float = BASE_COMMISSION_PIPS_ROUND_TRIP,
) -> dict[str, Any]:
    timestamps = index.timestamps
    start = bisect_left(timestamps, pd.Timestamp(ensure_utc(submit_at)))
    end = bisect_left(timestamps, pd.Timestamp(ensure_utc(cancel_at)))
    half_spread = 0.5 * float(spread_pips) * PIP_SIZE
    if end <= start:
        return {
            "parent_id": parent_id,
            "slot": slot,
            "status": "MISSED",
            "reason": "NO_PENDING_WINDOW",
            "submit_at": ensure_utc(submit_at).isoformat(),
            "cancel_at": ensure_utc(cancel_at).isoformat(),
        }

    if direction == "LONG":
        mask = index.lows[start:end] <= float(entry) - half_spread
    else:
        mask = index.highs[start:end] >= float(entry) + half_spread
    hits = np.flatnonzero(mask)
    if len(hits) == 0:
        return {
            "parent_id": parent_id,
            "slot": slot,
            "direction": direction,
            "status": "MISSED",
            "reason": "LIMIT_NOT_FILLED",
            "submit_at": ensure_utc(submit_at).isoformat(),
            "cancel_at": ensure_utc(cancel_at).isoformat(),
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target),
            "activation": activation,
        }

    fill_i = start + int(hits[0])
    fill_at = ensure_utc(timestamps[fill_i].to_pydatetime())
    risk_pips = (
        (float(entry) - float(stop)) / PIP_SIZE
        if direction == "LONG"
        else (float(stop) - float(entry)) / PIP_SIZE
    )
    if risk_pips <= 0:
        return {
            "parent_id": parent_id,
            "slot": slot,
            "status": "INVALID",
            "reason": "INVALID_RISK_GEOMETRY",
        }

    last_i = len(timestamps) - 1
    exit_i = None
    exit_price = None
    outcome = "OPEN"
    reason = "DATA_END"
    ambiguous = False
    for i in range(fill_i, len(timestamps)):
        if direction == "LONG":
            stop_hit = float(index.lows[i]) - half_spread <= float(stop)
            raw_target_hit = float(index.highs[i]) - half_spread >= float(target)
        else:
            stop_hit = float(index.highs[i]) + half_spread >= float(stop)
            raw_target_hit = float(index.lows[i]) + half_spread <= float(target)
        target_hit = raw_target_hit if i > fill_i else False
        ambiguous = bool(stop_hit and raw_target_hit)
        if stop_hit:
            exit_i = i
            exit_price = float(stop)
            outcome = "LOSS"
            reason = "STOP_FIRST_AMBIGUOUS" if ambiguous else "STOP_HIT"
            break
        if target_hit:
            exit_i = i
            exit_price = float(target)
            outcome = "WIN"
            reason = "TARGET_HIT"
            break

    if exit_i is None:
        exit_i = last_i
        exit_price = float(index.closes[last_i])
        gross_side = (
            exit_price - float(entry)
            if direction == "LONG"
            else float(entry) - exit_price
        )
        outcome = "WIN" if gross_side > 0 else "LOSS" if gross_side < 0 else "BREAKEVEN"
        reason = "FORCED_DATA_END"

    gross_price = (
        float(exit_price) - float(entry)
        if direction == "LONG"
        else float(entry) - float(exit_price)
    )
    gross_pips = gross_price / PIP_SIZE
    cost_pips = float(slippage_pips) + float(commission_pips)
    net_pips = gross_pips - cost_pips
    pnl = net_pips * 0.10
    risk_dollars = risk_pips * 0.10
    net_r = pnl / risk_dollars if risk_dollars > 0 else None
    return {
        "parent_id": parent_id,
        "slot": int(slot),
        "direction": direction,
        "status": "CLOSED",
        "outcome": outcome,
        "reason": reason,
        "activation": activation,
        "submit_at": ensure_utc(submit_at).isoformat(),
        "cancel_at": ensure_utc(cancel_at).isoformat(),
        "fill_at": fill_at.isoformat(),
        "exit_at": ensure_utc(timestamps[exit_i].to_pydatetime()).isoformat(),
        "entry": float(entry),
        "stop": float(stop),
        "target": float(target),
        "exit_price": float(exit_price),
        "risk_pips": float(risk_pips),
        "gross_pips": float(gross_pips),
        "cost_pips": float(cost_pips),
        "net_pips": float(net_pips),
        "risk_dollars": float(risk_dollars),
        "net_pnl": float(pnl),
        "net_r": None if net_r is None else float(net_r),
        "margin_required_1_100": float(CHILD_UNITS * float(entry) / 100.0),
        "ambiguous_bar": bool(ambiguous),
    }


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
    prior_mode: str,
    arm_mode: str,
) -> dict[str, Any]:
    mode = str(prior_mode).upper()
    if mode == "CURRENT":
        prior = CURRENT_PRIOR
        hierarchy = CURRENT_HIERARCHY
    elif mode == "SEED_2012_2018":
        prior = SEED_2012_2018_PRIOR
        hierarchy = SEED_2012_2018_HIERARCHY
    else:
        raise ValueError(f"unknown prior mode: {prior_mode}")
    arm = str(arm_mode).upper()
    if arm not in {"LITERAL", "HEALTHY_1ATR"}:
        raise ValueError(f"unknown arm mode: {arm_mode}")

    plans, zones, superseded, invalidated = _parent_plans(
        price_m1,
        target_year=target_year,
        prior=prior,
        hierarchy=hierarchy,
        arm_mode=arm,
    )
    index = _price_index(price_m1)
    m5_frame = _resample_ohlc(price_m1, "5min")
    m5_bars = _bars_from_frame(m5_frame, "M5")
    children: list[dict[str, Any]] = []

    for plan in plans:
        cancel_at = ensure_utc(plan["cancel_at"])
        for child in plan["children"][:2]:
            target = _f(child.get("planned_target"))
            if target is None:
                continue
            row = _simulate_child(
                price_m1,
                index=index,
                parent_id=str(plan["parent_id"]),
                slot=int(child["slot"]),
                direction=str(plan["direction"]),
                submit_at=ensure_utc(plan["plan_at"]),
                cancel_at=cancel_at,
                entry=float(child["reference_entry"]),
                stop=float(plan["stop"]),
                target=float(target),
                activation="PRE_TOUCH_LIMIT",
            )
            children.append(row)

        for micro in _m5_submission_orders(
            plan=plan,
            m5_bars=m5_bars,
            zones=zones,
            superseded=superseded,
            invalidated=invalidated,
        ):
            row = _simulate_child(
                price_m1,
                index=index,
                parent_id=str(plan["parent_id"]),
                slot=int(micro["slot"]),
                direction=str(plan["direction"]),
                submit_at=ensure_utc(micro["submit_at"]),
                cancel_at=cancel_at,
                entry=float(micro["entry"]),
                stop=float(plan["stop"]),
                target=float(micro["target"]),
                activation=str(micro["activation"]),
            )
            children.append(row)

    closed = [row for row in children if row.get("status") == "CLOSED"]
    missed = [row for row in children if row.get("status") == "MISSED"]
    return {
        "research_version": RESEARCH_VERSION,
        "pair": SYMBOL,
        "year": int(target_year),
        "prior_mode": mode,
        "arm_mode": arm,
        "plan_count": len(plans),
        "child_records": children,
        "closed_children": len(closed),
        "missed_children": len(missed),
        "gross_net_pnl_if_all_fills_allowed": float(sum(float(row.get("net_pnl") or 0.0) for row in closed)),
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_structural_targets_v229 import build_structural_target_plan
from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .models import Bar, ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    OBSERVATION_HOURS,
    SDZone,
    _active_at,
    _first_invalidation_at,
    _load_price_frame,
    _overlaps,
    _price_index,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "XAU_RIZAN_STRATEGY_V230_1"
ARTIFACT_CONTRACT = "XAU_RIZAN_STRATEGY_V230_1_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
CHILD_LOT = 0.01
XAU_OZ_PER_CHILD = 1.0  # standard 100 oz contract * 0.01 lot
H4_STOP_BUFFER_ATR = 0.15
MIN_TERMINAL_RR = 1.50
PARENT_TTL_HOURS = 16
MAX_PORTFOLIO_CHILDREN = 10
LADDER_QUANTILES = (0.10, 0.35, 0.60, 0.85)

# Frozen V225.2 full-sample causal-close priors used by the current V226/V229
# production map. This makes V230 a retrospective parameter replay, not an OOS
# estimate. A walk-forward refit is deliberately a separate experiment.
REVERSAL_COUNTS = {
    "H4": {
        "LONG": (563, 286, 221, 162, 129, 113, 90, 72, 59, 38),
        "SHORT": (559, 276, 211, 143, 110, 103, 88, 56, 58, 34),
    },
    "H1": {
        "LONG": (1583, 891, 658, 493, 381, 270, 268, 217, 178, 133),
        "SHORT": (1520, 867, 582, 480, 367, 321, 248, 216, 167, 139),
    },
    "M15": {
        "LONG": (5355, 3142, 2168, 1656, 1304, 1052, 893, 680, 550, 491),
        "SHORT": (5357, 3139, 2168, 1592, 1244, 963, 855, 715, 574, 479),
    },
}
H1_NESTED = {"p25": 0.1705211224175521, "median": 0.3740740740740644, "p75": 0.6441281138789966}
M15_NESTED = {"p25": 0.22012867647070358, "median": 0.4620542672722867, "p75": 0.7175662878788179}


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _histogram_quantile_depth(timeframe: str, direction: str, q: float) -> float:
    counts = REVERSAL_COUNTS[str(timeframe).upper()][str(direction).upper()]
    total = sum(counts)
    threshold = float(q) * total
    running = 0
    for index, count in enumerate(counts):
        if running + count >= threshold:
            within = (threshold - running) / max(count, 1)
            return index / 10.0 + within * 0.10
        running += count
    return 0.999999


def frozen_ladder_depths(timeframe: str, direction: str) -> tuple[float, float, float, float]:
    return tuple(
        _histogram_quantile_depth(timeframe, direction, q)
        for q in LADDER_QUANTILES
    )  # type: ignore[return-value]


def _zone_dict(zone: SDZone) -> dict[str, Any]:
    payload = asdict(zone)
    for key in ("available_at", "origin_at", "departure_at"):
        payload[key] = ensure_utc(payload[key]).isoformat()
    payload["lifecycle"] = {"active": True}
    payload["status"] = "V230_CAUSAL_ACTIVE"
    return payload


def _distance_to_zone(price: float, zone: SDZone) -> float:
    if price < float(zone.low):
        return float(zone.low) - price
    if price > float(zone.high):
        return price - float(zone.high)
    return 0.0


def _overlap_bounds(
    low_a: float, high_a: float, low_b: float, high_b: float
) -> tuple[float, float] | None:
    low = max(float(low_a), float(low_b))
    high = min(float(high_a), float(high_b))
    return None if high <= low else (low, high)


def _depth_price(zone: SDZone, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    width = float(zone.high) - float(zone.low)
    return (
        float(zone.high) - d * width
        if zone.direction == "LONG"
        else float(zone.low) + d * width
    )


def _depth_envelope(zone: SDZone, p25: float, p75: float) -> dict[str, float]:
    a = _depth_price(zone, p25)
    b = _depth_price(zone, p75)
    return {"low": min(a, b), "high": max(a, b)}


def _clip_envelope(
    envelope: dict[str, float],
    parent: dict[str, float] | SDZone,
) -> dict[str, float]:
    p_low = float(parent["low"]) if isinstance(parent, dict) else float(parent.low)
    p_high = float(parent["high"]) if isinstance(parent, dict) else float(parent.high)
    overlap = _overlap_bounds(
        float(envelope["low"]), float(envelope["high"]), p_low, p_high
    )
    if overlap is None:
        return {}
    return {"low": overlap[0], "high": overlap[1]}


def _hotspot_h4(zone: SDZone) -> dict[str, float]:
    # Frozen V225.2 top hazard band is 00-10% for both H4 directions.
    a = _depth_price(zone, 0.0)
    b = _depth_price(zone, 0.10)
    return {"low": min(a, b), "high": max(a, b)}


def _price_before(frame: pd.DataFrame, at: datetime) -> float | None:
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    idx = int(timestamps.searchsorted(pd.Timestamp(ensure_utc(at)), side="left")) - 1
    if idx < 0:
        return None
    return float(frame.iloc[idx]["close"])


def _zone_first_touches(
    price_m1: pd.DataFrame,
    zones: Sequence[SDZone],
    *,
    superseded: dict[str, datetime | None],
) -> dict[str, datetime | None]:
    index = _price_index(price_m1)
    out: dict[str, datetime | None] = {}
    for zone in zones:
        if zone.timeframe != "H4":
            continue
        episode = evaluate_first_touch(
            price_m1,
            zone=zone,
            index=index,
            valid_until=superseded.get(zone.zone_id),
        )
        out[zone.zone_id] = None if episode is None else ensure_utc(episode.touch_at)
    return out


def _select_fresh_h4(
    zones: Sequence[SDZone],
    *,
    at: datetime,
    price: float,
    first_touch: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> SDZone | None:
    candidates = []
    for zone in zones:
        if zone.timeframe != "H4":
            continue
        if not _active_at(zone, invalidated, superseded, at):
            continue
        touch_at = first_touch.get(zone.zone_id)
        if touch_at is not None and touch_at <= ensure_utc(at):
            continue
        if zone.direction == "LONG" and not price > float(zone.high):
            continue
        if zone.direction == "SHORT" and not price < float(zone.low):
            continue
        candidates.append(zone)
    if not candidates:
        return None
    candidates.sort(
        key=lambda z: (
            _distance_to_zone(price, z),
            float(z.high) - float(z.low),
            -ensure_utc(z.available_at).timestamp(),
        )
    )
    return candidates[0]


def _select_h1(
    zones: Sequence[SDZone],
    *,
    parent: SDZone,
    hotspot: dict[str, float],
    direction: str,
    price: float,
    at: datetime,
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> SDZone | None:
    candidates = []
    for zone in zones:
        if zone.timeframe != "H1" or zone.direction != direction:
            continue
        if not _active_at(zone, invalidated, superseded, at):
            continue
        if not _overlaps(parent, zone):
            continue
        overlap = _overlap_bounds(
            float(hotspot["low"]),
            float(hotspot["high"]),
            float(zone.low),
            float(zone.high),
        )
        overlap_width = 0.0 if overlap is None else overlap[1] - overlap[0]
        candidates.append((zone, overlap_width))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -int(item[1] > 0),
            -item[1],
            _distance_to_zone(price, item[0]),
            float(item[0].high) - float(item[0].low),
            -ensure_utc(item[0].available_at).timestamp(),
        )
    )
    return candidates[0][0]


def _select_m15(
    zones: Sequence[SDZone],
    *,
    parent: SDZone,
    locator: dict[str, float],
    direction: str,
    price: float,
    at: datetime,
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> SDZone | None:
    candidates = []
    for zone in zones:
        if zone.timeframe != "M15" or zone.direction != direction:
            continue
        if not _active_at(zone, invalidated, superseded, at):
            continue
        if not _overlaps(parent, zone):
            continue
        overlap = _overlap_bounds(
            float(locator["low"]),
            float(locator["high"]),
            float(zone.low),
            float(zone.high),
        )
        overlap_width = 0.0 if overlap is None else overlap[1] - overlap[0]
        candidates.append((zone, overlap_width))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -int(item[1] > 0),
            -item[1],
            _distance_to_zone(price, item[0]),
            float(item[0].high) - float(item[0].low),
            -ensure_utc(item[0].available_at).timestamp(),
        )
    )
    return candidates[0][0]


def _candidate_geometry(
    *,
    h4: SDZone,
    h1: SDZone | None,
    m15: SDZone | None,
) -> tuple[str, dict[str, float]]:
    h4_hotspot = _hotspot_h4(h4)
    h1_nested: dict[str, float] = {}
    if h1 is not None:
        h1_nested = _clip_envelope(
            _depth_envelope(h1, H1_NESTED["p25"], H1_NESTED["p75"]),
            h4,
        )
    m15_nested: dict[str, float] = {}
    if m15 is not None:
        parent = h1_nested or h4_hotspot
        m15_nested = _clip_envelope(
            _depth_envelope(m15, M15_NESTED["p25"], M15_NESTED["p75"]),
            parent,
        )
    if m15_nested:
        return "M15", m15_nested
    if h1_nested:
        return "H1", h1_nested
    return "H4", h4_hotspot


def _ladder_entries(
    *,
    direction: str,
    source_timeframe: str,
    candidate: dict[str, float],
) -> tuple[float, float, float, float]:
    low = float(candidate["low"])
    high = float(candidate["high"])
    width = high - low
    depths = frozen_ladder_depths(source_timeframe, direction)
    prices = [
        high - depth * width if direction == "LONG" else low + depth * width
        for depth in depths
    ]
    return tuple(prices)  # type: ignore[return-value]


def _active_zone_dicts(
    zones: Sequence[SDZone],
    *,
    at: datetime,
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    m15: list[dict[str, Any]] = []
    htf: list[dict[str, Any]] = []
    for zone in zones:
        if zone.timeframe not in {"M15", "H1", "H4"}:
            continue
        if not _active_at(zone, invalidated, superseded, at):
            continue
        payload = _zone_dict(zone)
        if zone.timeframe == "M15":
            m15.append(payload)
        else:
            htf.append(payload)
    return m15, htf


def _target_for_slot(
    *,
    slot: int,
    direction: str,
    entry: float,
    stop: float,
    at: datetime,
    zones: Sequence[SDZone],
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> tuple[float | None, str | None, dict[str, Any]]:
    m15, htf = _active_zone_dicts(
        zones, at=at, invalidated=invalidated, superseded=superseded
    )
    structural = build_structural_target_plan(
        direction=direction,
        entry=entry,
        stop=stop,
        m15_zones=m15,
        htf_zones=htf,
        minimum_rr=MIN_TERMINAL_RR,
    )
    targets = [dict(x) for x in list(structural.get("broker_scaleout_targets") or [])]
    if not targets:
        return None, None, structural
    if slot == 1:
        chosen = targets[0]
    elif slot == 2 and len(targets) >= 2:
        chosen = targets[1]
    else:
        chosen = targets[-1]
    return _f(chosen.get("target_price")), str(chosen.get("timeframe") or ""), structural


def _time_bound(
    touch_at: datetime,
    h4: SDZone,
    *,
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> datetime:
    bound = ensure_utc(touch_at) + timedelta(hours=PARENT_TTL_HOURS)
    for raw in (invalidated.get(h4.zone_id), superseded.get(h4.zone_id)):
        if raw is not None and ensure_utc(raw) < bound:
            bound = ensure_utc(raw)
    return bound


def _first_cross(
    price_m1: pd.DataFrame,
    *,
    level: float,
    start_at: datetime,
    end_at: datetime,
) -> datetime | None:
    timestamps = pd.DatetimeIndex(price_m1["timestamp"])
    start = int(timestamps.searchsorted(pd.Timestamp(start_at), side="left"))
    end = int(timestamps.searchsorted(pd.Timestamp(end_at), side="right"))
    if end <= start:
        return None
    rows = price_m1.iloc[start:end]
    mask = (rows["low"].to_numpy(float) <= float(level)) & (
        rows["high"].to_numpy(float) >= float(level)
    )
    hits = np.flatnonzero(mask)
    if len(hits) == 0:
        return None
    return ensure_utc(pd.Timestamp(rows.iloc[int(hits[0])]["timestamp"]).to_pydatetime())


def _exit_child(
    price_m1: pd.DataFrame,
    *,
    direction: str,
    fill_at: datetime,
    entry: float,
    stop: float,
    target: float,
    end_at: datetime,
) -> dict[str, Any]:
    timestamps = pd.DatetimeIndex(price_m1["timestamp"])
    start = int(timestamps.searchsorted(pd.Timestamp(fill_at), side="left"))
    end = int(timestamps.searchsorted(pd.Timestamp(end_at), side="right"))
    if end <= start:
        return {
            "outcome": "NO_POST_FILL_DATA",
            "exit_at": ensure_utc(fill_at).isoformat(),
            "exit_price": entry,
            "pnl_r": 0.0,
            "pnl_usd": 0.0,
        }
    rows = price_m1.iloc[start:end]
    lows = rows["low"].to_numpy(float)
    highs = rows["high"].to_numpy(float)
    if direction == "LONG":
        sl_mask = lows <= stop
        tp_mask = highs >= target
        risk = entry - stop
    else:
        sl_mask = highs >= stop
        tp_mask = lows <= target
        risk = stop - entry
    if risk <= 0:
        raise RuntimeError("V230_NONPOSITIVE_CHILD_RISK")
    events = np.flatnonzero(sl_mask | tp_mask)
    if len(events):
        rel = int(events[0])
        # Conservative same-M1 ambiguity: stop wins.
        if bool(sl_mask[rel]):
            outcome = "SL"
            exit_price = stop
        else:
            outcome = "TP"
            exit_price = target
        exit_at = ensure_utc(pd.Timestamp(rows.iloc[rel]["timestamp"]).to_pydatetime())
    else:
        outcome = "TIMEOUT"
        exit_price = float(rows.iloc[-1]["close"])
        exit_at = ensure_utc(pd.Timestamp(rows.iloc[-1]["timestamp"]).to_pydatetime())
    pnl_points = (
        exit_price - entry if direction == "LONG" else entry - exit_price
    )
    return {
        "outcome": outcome,
        "exit_at": exit_at.isoformat(),
        "exit_price": float(exit_price),
        "pnl_r": float(pnl_points / risk),
        "pnl_usd": float(pnl_points * XAU_OZ_PER_CHILD),
    }


def _bars_m5(price_m1: pd.DataFrame) -> tuple[Bar, ...]:
    frame = (
        price_m1.set_index("timestamp")
        .resample("5min", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )
    return tuple(
        Bar(
            symbol="XAUUSD",
            timeframe="M5",
            timestamp=ensure_utc(pd.Timestamp(row.timestamp).to_pydatetime()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_count=1,
            spread_avg=0.0,
            spread_max=0.0,
        )
        for row in frame.itertuples(index=False)
    )


def _micro_activation(
    *,
    slot: int,
    direction: str,
    h1: SDZone | None,
    h4: SDZone,
    touch_at: datetime,
    end_at: datetime,
    m5_bars: Sequence[Bar],
) -> tuple[datetime | None, float | None, str]:
    if h1 is None:
        return None, None, "NO_H1_SOURCE"
    source = _zone_dict(h1)
    parent = _zone_dict(h4)
    path_map = {
        "active_path": {
            "source_zone": source,
            "reaction_direction": direction,
        }
    }
    start_window = ensure_utc(touch_at) - timedelta(hours=14)
    relevant = [
        bar
        for bar in m5_bars
        if ensure_utc(bar.timestamp) >= start_window
        and ensure_utc(bar.timestamp) < ensure_utc(end_at)
    ]
    for bar in relevant:
        close_at = ensure_utc(bar.timestamp) + timedelta(minutes=5)
        if close_at < ensure_utc(touch_at) or close_at > ensure_utc(end_at):
            continue
        state = evaluate_micro_refinement(
            relevant,
            path_map=path_map,
            as_of=close_at,
            parent_source_zone=parent,
        )
        if str(state.get("direction") or "").upper() != direction:
            continue
        if slot == 3:
            if not bool(state.get("reclaim_confirmed")) or not bool(state.get("mss_confirmed")):
                continue
            pocket = dict(state.get("candidate_entry_pocket") or {})
            price = _f(pocket.get("high" if direction == "LONG" else "low"))
            if price is not None:
                return close_at, price, "M5_RECLAIM_MSS_RETEST"
        else:
            if not bool(state.get("displacement_confirmed")):
                continue
            pocket = dict(state.get("refined_entry_pocket") or {})
            price = _f(pocket.get("high" if direction == "LONG" else "low"))
            if price is not None:
                return close_at, price, "M5_DISPLACEMENT_RETEST"
    return None, None, "M5_CONFIRMATION_NOT_REACHED"


def _child_record(
    *,
    signal_key: str,
    slot: int,
    direction: str,
    placed_at: datetime,
    entry: float,
    stop: float,
    target: float | None,
    target_timeframe: str | None,
    activation: str,
    fill_at: datetime | None,
    exit_record: dict[str, Any] | None,
) -> dict[str, Any]:
    base = {
        "signal_key": signal_key,
        "slot": int(slot),
        "lot": CHILD_LOT,
        "direction": direction,
        "placed_at": ensure_utc(placed_at).isoformat(),
        "entry": float(entry),
        "sl": float(stop),
        "tp": None if target is None else float(target),
        "target_timeframe": target_timeframe,
        "activation": activation,
        "fill_at": None if fill_at is None else ensure_utc(fill_at).isoformat(),
    }
    if fill_at is None:
        return base | {
            "outcome": "UNFILLED",
            "exit_at": None,
            "exit_price": None,
            "pnl_r": 0.0,
            "pnl_usd": 0.0,
        }
    return base | dict(exit_record or {})


def simulate_year(
    price_m1: pd.DataFrame,
    *,
    target_year: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
    first_touch = _zone_first_touches(price_m1, zones, superseded=superseded)
    m5_bars = _bars_m5(price_m1)

    h4_events = []
    for zone in zones:
        if zone.timeframe != "H4":
            continue
        episode = evaluate_first_touch(
            price_m1,
            zone=zone,
            index=index,
            valid_until=superseded.get(zone.zone_id),
        )
        if (
            episode is not None
            and ensure_utc(episode.touch_at).year == int(target_year)
        ):
            h4_events.append((zone, episode))
    h4_events.sort(key=lambda item: ensure_utc(item[1].touch_at))

    records: list[dict[str, Any]] = []
    selected_parent_count = 0
    target_eligible_count = 0

    for h4, episode in h4_events:
        touch_at = ensure_utc(episode.touch_at)
        decision_at = touch_at - timedelta(minutes=1)
        reference_price = _price_before(price_m1, touch_at)
        if reference_price is None:
            continue
        selected_h4 = _select_fresh_h4(
            zones,
            at=decision_at,
            price=reference_price,
            first_touch=first_touch,
            invalidated=invalidated,
            superseded=superseded,
        )
        if selected_h4 is None or selected_h4.zone_id != h4.zone_id:
            continue
        selected_parent_count += 1

        direction = h4.direction
        hotspot = _hotspot_h4(h4)
        h1 = _select_h1(
            zones,
            parent=h4,
            hotspot=hotspot,
            direction=direction,
            price=reference_price,
            at=decision_at,
            invalidated=invalidated,
            superseded=superseded,
        )
        h1_locator = (
            {}
            if h1 is None
            else _clip_envelope(
                _depth_envelope(h1, H1_NESTED["p25"], H1_NESTED["p75"]),
                h4,
            )
        )
        m15_parent = h1 or h4
        m15_locator_parent = h1_locator or hotspot
        m15 = _select_m15(
            zones,
            parent=m15_parent,
            locator=m15_locator_parent,
            direction=direction,
            price=reference_price,
            at=decision_at,
            invalidated=invalidated,
            superseded=superseded,
        )
        source_tf, candidate = _candidate_geometry(h4=h4, h1=h1, m15=m15)
        if not candidate:
            continue
        entries = _ladder_entries(
            direction=direction,
            source_timeframe=source_tf,
            candidate=candidate,
        )
        stop = (
            float(h4.low) - H4_STOP_BUFFER_ATR * float(h4.atr_points)
            if direction == "LONG"
            else float(h4.high) + H4_STOP_BUFFER_ATR * float(h4.atr_points)
        )
        end_at = _time_bound(
            touch_at, h4, invalidated=invalidated, superseded=superseded
        )
        signal_key = "|".join(
            (
                str(target_year),
                ensure_utc(touch_at).isoformat(),
                direction,
                h4.zone_id,
                source_tf,
            )
        )
        children: list[dict[str, Any]] = []

        # Slots 1-2 are pre-touch LIMIT orders.
        for slot in (1, 2):
            entry = float(entries[slot - 1])
            target, target_tf, structural = _target_for_slot(
                slot=slot,
                direction=direction,
                entry=entry,
                stop=stop,
                at=decision_at,
                zones=zones,
                invalidated=invalidated,
                superseded=superseded,
            )
            if target is None or not bool(structural.get("terminal_rr_eligible")):
                children.append(
                    _child_record(
                        signal_key=signal_key,
                        slot=slot,
                        direction=direction,
                        placed_at=decision_at,
                        entry=entry,
                        stop=stop,
                        target=None,
                        target_timeframe=None,
                        activation="PRE_TOUCH_LIMIT_NO_STRUCTURAL_TP",
                        fill_at=None,
                        exit_record=None,
                    )
                )
                continue
            target_eligible_count += 1
            fill_at = _first_cross(
                price_m1,
                level=entry,
                start_at=decision_at,
                end_at=end_at,
            )
            exit_record = (
                None
                if fill_at is None
                else _exit_child(
                    price_m1,
                    direction=direction,
                    fill_at=fill_at,
                    entry=entry,
                    stop=stop,
                    target=float(target),
                    end_at=touch_at + timedelta(hours=PARENT_TTL_HOURS),
                )
            )
            children.append(
                _child_record(
                    signal_key=signal_key,
                    slot=slot,
                    direction=direction,
                    placed_at=decision_at,
                    entry=entry,
                    stop=stop,
                    target=float(target),
                    target_timeframe=target_tf,
                    activation="PRE_TOUCH_LIMIT",
                    fill_at=fill_at,
                    exit_record=exit_record,
                )
            )

        # Slots 3-4 only become orders after causal completed-M5 evidence.
        for slot in (3, 4):
            activation_at, retest_entry, activation = _micro_activation(
                slot=slot,
                direction=direction,
                h1=h1,
                h4=h4,
                touch_at=touch_at,
                end_at=end_at,
                m5_bars=m5_bars,
            )
            if activation_at is None or retest_entry is None:
                children.append(
                    _child_record(
                        signal_key=signal_key,
                        slot=slot,
                        direction=direction,
                        placed_at=touch_at,
                        entry=float(entries[slot - 1]),
                        stop=stop,
                        target=None,
                        target_timeframe=None,
                        activation=activation,
                        fill_at=None,
                        exit_record=None,
                    )
                )
                continue
            target, target_tf, structural = _target_for_slot(
                slot=slot,
                direction=direction,
                entry=float(retest_entry),
                stop=stop,
                at=activation_at,
                zones=zones,
                invalidated=invalidated,
                superseded=superseded,
            )
            if target is None or not bool(structural.get("terminal_rr_eligible")):
                children.append(
                    _child_record(
                        signal_key=signal_key,
                        slot=slot,
                        direction=direction,
                        placed_at=activation_at,
                        entry=float(retest_entry),
                        stop=stop,
                        target=None,
                        target_timeframe=None,
                        activation=f"{activation}_NO_STRUCTURAL_TP",
                        fill_at=None,
                        exit_record=None,
                    )
                )
                continue
            target_eligible_count += 1
            fill_at = _first_cross(
                price_m1,
                level=float(retest_entry),
                start_at=activation_at,
                end_at=end_at,
            )
            exit_record = (
                None
                if fill_at is None
                else _exit_child(
                    price_m1,
                    direction=direction,
                    fill_at=fill_at,
                    entry=float(retest_entry),
                    stop=stop,
                    target=float(target),
                    end_at=touch_at + timedelta(hours=PARENT_TTL_HOURS),
                )
            )
            children.append(
                _child_record(
                    signal_key=signal_key,
                    slot=slot,
                    direction=direction,
                    placed_at=activation_at,
                    entry=float(retest_entry),
                    stop=stop,
                    target=float(target),
                    target_timeframe=target_tf,
                    activation=activation,
                    fill_at=fill_at,
                    exit_record=exit_record,
                )
            )

        records.append(
            {
                "signal_key": signal_key,
                "year": int(target_year),
                "touch_at": touch_at.isoformat(),
                "direction": direction,
                "h4_zone_id": h4.zone_id,
                "h1_zone_id": None if h1 is None else h1.zone_id,
                "m15_zone_id": None if m15 is None else m15.zone_id,
                "source_timeframe": source_tf,
                "candidate_low": float(candidate["low"]),
                "candidate_high": float(candidate["high"]),
                "stop": float(stop),
                "parent_end_at": end_at.isoformat(),
                "children": children,
            }
        )

    summary = summarize_signal_records(records)
    summary["h4_first_touch_events"] = len(h4_events)
    summary["causal_selected_h4_parents"] = selected_parent_count
    summary["target_eligible_child_plans"] = target_eligible_count
    summary["selection_contract"] = (
        "H4 focus uses V226 no-projection fallback: globally nearest fresh causal H4 "
        "parent one minute before first touch. H1/M15 are selected from zones already "
        "available and active at that time; later reversal outcome coordinates are never used for selection."
    )
    return summary, records


def _flatten_children(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for signal in records:
        for raw in list(signal.get("children") or []):
            child = dict(raw)
            child["year"] = int(signal.get("year") or 0)
            output.append(child)
    return output


def apply_account_cap(
    records: Sequence[dict[str, Any]],
    *,
    cap: int = MAX_PORTFOLIO_CHILDREN,
) -> list[dict[str, Any]]:
    children = [row for row in _flatten_children(records) if row.get("fill_at")]
    children.sort(
        key=lambda row: (
            str(row.get("fill_at")),
            str(row.get("signal_key")),
            int(row.get("slot") or 0),
        )
    )
    active: list[datetime] = []
    accepted: list[dict[str, Any]] = []
    for child in children:
        fill_at = ensure_utc(datetime.fromisoformat(str(child["fill_at"]).replace("Z", "+00:00")))
        active = [value for value in active if value > fill_at]
        if len(active) >= int(cap):
            accepted.append({**child, "account_cap_accepted": False})
            continue
        exit_raw = child.get("exit_at")
        exit_at = (
            fill_at
            if not exit_raw
            else ensure_utc(datetime.fromisoformat(str(exit_raw).replace("Z", "+00:00")))
        )
        active.append(exit_at)
        accepted.append({**child, "account_cap_accepted": True})
    return accepted


def _max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def summarize_signal_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    signals = list(records)
    all_children = _flatten_children(signals)
    filled = [row for row in all_children if row.get("fill_at")]
    accepted_rows = apply_account_cap(signals)
    accepted = [row for row in accepted_rows if bool(row.get("account_cap_accepted"))]
    accepted.sort(key=lambda row: str(row.get("exit_at") or row.get("fill_at") or ""))

    pnls_r = [float(row.get("pnl_r") or 0.0) for row in accepted]
    pnls_usd = [float(row.get("pnl_usd") or 0.0) for row in accepted]
    gross_profit_r = sum(value for value in pnls_r if value > 0)
    gross_loss_r = -sum(value for value in pnls_r if value < 0)
    signal_pnl: dict[str, float] = {}
    for row in accepted:
        key = str(row.get("signal_key") or "")
        signal_pnl[key] = signal_pnl.get(key, 0.0) + float(row.get("pnl_usd") or 0.0)

    by_slot: dict[str, dict[str, Any]] = {}
    for slot in range(1, 5):
        rows = [row for row in accepted if int(row.get("slot") or 0) == slot]
        by_slot[str(slot)] = {
            "fills": len(rows),
            "tp": sum(str(row.get("outcome")) == "TP" for row in rows),
            "sl": sum(str(row.get("outcome")) == "SL" for row in rows),
            "timeout": sum(str(row.get("outcome")) == "TIMEOUT" for row in rows),
            "total_r": sum(float(row.get("pnl_r") or 0.0) for row in rows),
            "total_pnl_usd": sum(float(row.get("pnl_usd") or 0.0) for row in rows),
        }

    return {
        "signals": len(signals),
        "signals_with_fill": len({str(row.get("signal_key")) for row in accepted}),
        "planned_children": len(all_children),
        "raw_filled_children": len(filled),
        "account_cap_accepted_children": len(accepted),
        "account_cap_rejected_children": sum(
            not bool(row.get("account_cap_accepted")) for row in accepted_rows
        ),
        "tp_children": sum(str(row.get("outcome")) == "TP" for row in accepted),
        "sl_children": sum(str(row.get("outcome")) == "SL" for row in accepted),
        "timeout_children": sum(str(row.get("outcome")) == "TIMEOUT" for row in accepted),
        "tp_rate_filled": None
        if not accepted
        else sum(str(row.get("outcome")) == "TP" for row in accepted) / len(accepted),
        "positive_child_rate": None
        if not accepted
        else sum(float(row.get("pnl_usd") or 0.0) > 0 for row in accepted) / len(accepted),
        "signal_positive_rate": None
        if not signal_pnl
        else sum(value > 0 for value in signal_pnl.values()) / len(signal_pnl),
        "total_r": sum(pnls_r),
        "mean_r_per_filled_child": None if not pnls_r else sum(pnls_r) / len(pnls_r),
        "median_r_per_filled_child": None if not pnls_r else median(pnls_r),
        "profit_factor_r": None if gross_loss_r <= 0 else gross_profit_r / gross_loss_r,
        "total_pnl_usd_0p01_standard_contract": sum(pnls_usd),
        "illustrative_start_balance_usd": 200.0,
        "illustrative_end_balance_usd": 200.0 + sum(pnls_usd),
        "max_drawdown_r": _max_drawdown(pnls_r),
        "max_drawdown_usd": _max_drawdown(pnls_usd),
        "by_slot": by_slot,
        "assumptions": {
            "child_lot": CHILD_LOT,
            "xau_oz_per_child": XAU_OZ_PER_CHILD,
            "spread_commission_slippage": "NOT_MODELED",
            "same_m1_sl_tp_ambiguity": "STOP_FIRST_CONSERVATIVE",
            "position_cap": MAX_PORTFOLIO_CHILDREN,
            "margin_cap": "NOT_MODELED",
            "compounding": False,
            "parent_ttl_hours": PARENT_TTL_HOURS,
        },
    }

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import mean
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .demo_xau_structural_targets_v229 import build_structural_target_plan
from .demo_xau_supply_demand_micro_refinement_v189 import evaluate_micro_refinement
from .demo_xau_v226_rizan_depth_map import _direction_map, _historical_hierarchy
from .models import Bar, ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    SDZone,
    _bars_from_frame,
    _first_invalidation_at,
    _load_price_frame,
    _price_index,
    _resample_ohlc,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "XAU_RIZAN_FOUR_CHILD_BACKTEST_V230_1"
ARTIFACT_CONTRACT = "XAU_RIZAN_FOUR_CHILD_BACKTEST_V230_1_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
FROZEN_PRIOR_VERSION = "XAU_ZONE_REVERSAL_DEPTH_V225_2"
FROZEN_PRIOR_CONTRACT = "XAU_ZONE_REVERSAL_DEPTH_V225_2_EVIDENCE_1_FULL_2012_2026_1"

SIGNAL_TTL_HOURS = 16.0
MAX_POSITION_HOLD_HOURS = 24.0 * 30.0
STOP_BUFFER_ATR = 0.15
MIN_TERMINAL_RR = 1.50
CHILD_LOT = 0.01
OZ_PER_001_LOT = 1.0
SAME_BAR_PRECEDENCE = "STOP_FIRST"
ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


@dataclass(slots=True)
class ChildResult:
    year: int
    parent_zone_id: str
    direction: str
    source_layer: str
    slot: int
    stage: str
    activation: str
    activated_at: datetime | None
    entry: float | None
    filled_at: datetime | None
    stop_loss: float
    take_profit: float | None
    target_timeframe: str | None
    target_zone_id: str | None
    exit_at: datetime | None
    exit_price: float | None
    outcome: str
    pnl_points: float | None
    pnl_usd_001: float | None
    r_multiple: float | None
    held_minutes: float | None


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _overlaps(a: SDZone, b: SDZone) -> bool:
    return min(float(a.high), float(b.high)) >= max(float(a.low), float(b.low))


def _zone_dict(
    zone: SDZone,
    *,
    as_of: datetime,
    first_touch_at: datetime | None,
    invalidated_at: datetime | None,
    superseded_at: datetime | None,
) -> dict[str, Any] | None:
    point = ensure_utc(as_of)
    available = ensure_utc(zone.available_at)
    if available > point:
        return None
    if invalidated_at is not None and ensure_utc(invalidated_at) <= point:
        return None
    if superseded_at is not None and ensure_utc(superseded_at) <= point:
        return None

    touched = first_touch_at is not None and ensure_utc(first_touch_at) < point
    lifecycle = {
        "active": True,
        "touch_count": 1 if touched else 0,
        "freshness": "FIRST_TEST" if touched else "FRESH",
        "invalidated_at": None if invalidated_at is None else ensure_utc(invalidated_at).isoformat(),
        "superseded_at": None if superseded_at is None else ensure_utc(superseded_at).isoformat(),
    }
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
        "available_at": available.isoformat(),
        "origin_at": ensure_utc(zone.origin_at).isoformat(),
        "departure_at": ensure_utc(zone.departure_at).isoformat(),
        "atr_points": float(zone.atr_points),
        "base_range_atr": float(zone.base_range_atr),
        "departure_range_atr": float(zone.departure_range_atr),
        "departure_body_fraction": float(zone.departure_body_fraction),
        "structural_bos": bool(zone.structural_bos),
        "lifecycle": lifecycle,
        "status": "ACTIVE",
        "execution_influence": False,
        "execution_authority": False,
    }


def _latest_close_before(price: pd.DataFrame, point: datetime) -> tuple[datetime, float] | None:
    timestamps = tuple(pd.Timestamp(x) for x in price["timestamp"])
    idx = bisect_left(timestamps, pd.Timestamp(ensure_utc(point))) - 1
    if idx < 0:
        return None
    return ensure_utc(timestamps[idx].to_pydatetime()), float(price.iloc[idx]["close"])


def _active_zone_dicts(
    zones: Sequence[SDZone],
    *,
    as_of: datetime,
    first_touch_by_zone: dict[str, datetime | None],
    invalidated_by_zone: dict[str, datetime | None],
    superseded_by_zone: dict[str, datetime | None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    htf: list[dict[str, Any]] = []
    m15: list[dict[str, Any]] = []
    for zone in zones:
        item = _zone_dict(
            zone,
            as_of=as_of,
            first_touch_at=first_touch_by_zone.get(zone.zone_id),
            invalidated_at=invalidated_by_zone.get(zone.zone_id),
            superseded_at=superseded_by_zone.get(zone.zone_id),
        )
        if item is None:
            continue
        if zone.timeframe == "M15":
            m15.append(item)
        elif zone.timeframe in {"H1", "H4"}:
            htf.append(item)
    return htf, m15


def _selected_h4_id(direction_map: dict[str, Any]) -> str:
    return str(
        dict(dict(direction_map.get("h4") or {}).get("zone") or {}).get("zone_id")
        or ""
    )


def _target_for_slot(
    *,
    slot: int,
    direction: str,
    entry: float,
    stop: float,
    htf_zones: Sequence[dict[str, Any]],
    m15_zones: Sequence[dict[str, Any]],
) -> tuple[float | None, str | None, str | None, dict[str, Any]]:
    plan = build_structural_target_plan(
        direction=direction,
        entry=float(entry),
        stop=float(stop),
        m15_zones=m15_zones,
        htf_zones=htf_zones,
        minimum_rr=MIN_TERMINAL_RR,
    )
    targets = [dict(x) for x in list(plan.get("broker_scaleout_targets") or [])]
    if not targets:
        return None, None, None, plan
    if slot == 1:
        chosen = targets[0]
    elif slot == 2 and len(targets) >= 2:
        chosen = targets[1]
    else:
        chosen = targets[-1]
    return (
        _f(chosen.get("target_price")),
        str(chosen.get("timeframe") or "") or None,
        str(chosen.get("zone_id") or "") or None,
        plan,
    )


def _limit_side_valid(direction: str, entry: float, live_price: float) -> bool:
    if direction == "LONG":
        return float(entry) < float(live_price)
    return float(entry) > float(live_price)


def _parent_cancel_at(
    *,
    decision_at: datetime,
    invalidated_at: datetime | None,
    superseded_at: datetime | None,
) -> datetime:
    candidates = [ensure_utc(decision_at) + timedelta(hours=SIGNAL_TTL_HOURS)]
    if invalidated_at is not None:
        candidates.append(ensure_utc(invalidated_at))
    if superseded_at is not None:
        candidates.append(ensure_utc(superseded_at))
    return min(candidates)


def _m5_activation(
    *,
    slot: int,
    direction: str,
    h1_source: dict[str, Any],
    h4_parent: dict[str, Any],
    m5_bars: Sequence[Bar],
    start_at: datetime,
    cancel_at: datetime,
) -> tuple[datetime, float, str] | None:
    if slot not in {3, 4} or not h1_source:
        return None
    timestamps = [ensure_utc(row.timestamp) for row in m5_bars]
    start_idx = max(0, bisect_left(timestamps, ensure_utc(start_at)) - 50)
    end_idx = bisect_right(timestamps, ensure_utc(cancel_at))
    path_map = {
        "active_path": {
            "source_zone": h1_source,
            "reaction_direction": direction,
        }
    }
    for idx in range(start_idx, end_idx):
        bar = m5_bars[idx]
        as_of = ensure_utc(bar.timestamp) + timedelta(minutes=5)
        if as_of < ensure_utc(start_at) or as_of > ensure_utc(cancel_at):
            continue
        prefix = m5_bars[max(0, idx - 180): idx + 1]
        micro = evaluate_micro_refinement(
            prefix,
            path_map=path_map,
            as_of=as_of,
            parent_source_zone=h4_parent,
        )
        if str(micro.get("direction") or "").upper() != direction:
            continue
        if slot == 3:
            if not bool(micro.get("reclaim_confirmed")) or not bool(micro.get("mss_confirmed")):
                continue
            pocket = dict(micro.get("candidate_entry_pocket") or {})
            entry = _f(pocket.get("high" if direction == "LONG" else "low"))
            activation = "M5_RECLAIM_MSS_RETEST"
        else:
            if not bool(micro.get("displacement_confirmed")):
                continue
            pocket = dict(micro.get("refined_entry_pocket") or {})
            entry = _f(pocket.get("high" if direction == "LONG" else "low"))
            activation = "M5_DISPLACEMENT_RETEST"
        if entry is None or not _limit_side_valid(direction, entry, float(bar.close)):
            continue
        return as_of, float(entry), activation
    return None


def _fill_index(
    px_index: Any,
    *,
    direction: str,
    entry: float,
    active_at: datetime,
    cancel_at: datetime,
) -> int | None:
    timestamps = px_index.timestamps
    start = bisect_left(timestamps, pd.Timestamp(ensure_utc(active_at)))
    end = bisect_left(timestamps, pd.Timestamp(ensure_utc(cancel_at)))
    if end <= start:
        return None
    if direction == "LONG":
        touched = px_index.lows[start:end] <= float(entry)
    else:
        touched = px_index.highs[start:end] >= float(entry)
    positions = np.flatnonzero(touched)
    return None if len(positions) == 0 else start + int(positions[0])


def _exit_after_fill(
    px_index: Any,
    *,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    fill_index: int,
) -> tuple[int, float, str]:
    timestamps = px_index.timestamps
    max_exit_at = ensure_utc(timestamps[fill_index].to_pydatetime()) + timedelta(
        hours=MAX_POSITION_HOLD_HOURS
    )
    end = min(len(timestamps), bisect_right(timestamps, pd.Timestamp(max_exit_at)))
    highs = px_index.highs[fill_index:end]
    lows = px_index.lows[fill_index:end]
    if direction == "LONG":
        stop_mask = lows <= float(stop)
        target_mask = highs >= float(target)
    else:
        stop_mask = highs >= float(stop)
        target_mask = lows <= float(target)
    events = np.flatnonzero(stop_mask | target_mask)
    if len(events):
        rel = int(events[0])
        absolute = fill_index + rel
        stop_hit = bool(stop_mask[rel])
        target_hit = bool(target_mask[rel])
        if stop_hit:
            return absolute, float(stop), "SL"
        if target_hit:
            return absolute, float(target), "TP"

    absolute = max(fill_index, end - 1)
    close = float(px_index.closes[absolute])
    if end >= len(timestamps):
        return absolute, close, "CENSORED_DATA_END"
    return absolute, close, "TIME_EXIT_30D_RESEARCH"


def _child_result(
    *,
    year: int,
    parent_zone_id: str,
    direction: str,
    source_layer: str,
    slot: int,
    stage: str,
    activation: str,
    activated_at: datetime | None,
    entry: float | None,
    stop: float,
    target: float | None,
    target_timeframe: str | None,
    target_zone_id: str | None,
    px_index: Any,
    cancel_at: datetime,
) -> ChildResult:
    if activated_at is None or entry is None or target is None:
        return ChildResult(
            year, parent_zone_id, direction, source_layer, slot, stage, activation,
            activated_at, entry, None, stop, target, target_timeframe, target_zone_id,
            None, None, "NOT_ACTIVATED_OR_NO_TARGET", None, None, None, None,
        )

    fill_idx = _fill_index(
        px_index,
        direction=direction,
        entry=entry,
        active_at=activated_at,
        cancel_at=cancel_at,
    )
    if fill_idx is None:
        return ChildResult(
            year, parent_zone_id, direction, source_layer, slot, stage, activation,
            activated_at, entry, None, stop, target, target_timeframe, target_zone_id,
            None, None, "CANCELLED_UNFILLED", None, None, None, None,
        )

    exit_idx, exit_price, outcome = _exit_after_fill(
        px_index,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        fill_index=fill_idx,
    )
    fill_at = ensure_utc(px_index.timestamps[fill_idx].to_pydatetime())
    exit_at = ensure_utc(px_index.timestamps[exit_idx].to_pydatetime())
    pnl = float(exit_price - entry) if direction == "LONG" else float(entry - exit_price)
    risk = float(entry - stop) if direction == "LONG" else float(stop - entry)
    r_multiple = None if risk <= 0 else pnl / risk
    return ChildResult(
        year=year,
        parent_zone_id=parent_zone_id,
        direction=direction,
        source_layer=source_layer,
        slot=slot,
        stage=stage,
        activation=activation,
        activated_at=activated_at,
        entry=float(entry),
        filled_at=fill_at,
        stop_loss=float(stop),
        take_profit=float(target),
        target_timeframe=target_timeframe,
        target_zone_id=target_zone_id,
        exit_at=exit_at,
        exit_price=float(exit_price),
        outcome=outcome,
        pnl_points=pnl,
        pnl_usd_001=pnl * OZ_PER_001_LOT,
        r_multiple=r_multiple,
        held_minutes=(exit_at - fill_at).total_seconds() / 60.0,
    )


def _serialize_child(row: ChildResult) -> dict[str, Any]:
    payload = asdict(row)
    for key in ("activated_at", "filled_at", "exit_at"):
        value = payload.get(key)
        payload[key] = None if value is None else ensure_utc(value).isoformat()
    return payload


def simulate_year(
    price: pd.DataFrame,
    *,
    target_year: int,
    history_details: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if str(history_details.get("research_version") or "") != FROZEN_PRIOR_VERSION:
        raise RuntimeError("V230_FROZEN_PRIOR_VERSION_MISMATCH")
    contract = str(history_details.get("contract") or "")
    if contract and contract != FROZEN_PRIOR_CONTRACT:
        raise RuntimeError("V230_FROZEN_PRIOR_CONTRACT_MISMATCH")

    zones = build_zones(price)
    px_index = _price_index(price)
    superseded = causal_superseded_at(zones)
    invalidated = {
        zone.zone_id: _first_invalidation_at(
            price,
            zone=zone,
            index=px_index,
            valid_until=superseded.get(zone.zone_id),
        )
        for zone in zones
    }
    first_episode: dict[str, Any] = {}
    first_touch_at: dict[str, datetime | None] = {}
    for zone in zones:
        episode = evaluate_first_touch(
            price,
            zone=zone,
            index=px_index,
            valid_until=superseded.get(zone.zone_id),
        )
        first_episode[zone.zone_id] = episode
        first_touch_at[zone.zone_id] = None if episode is None else ensure_utc(episode.touch_at)

    h4_episodes = [
        first_episode[zone.zone_id]
        for zone in zones
        if zone.timeframe == "H4"
        and first_episode.get(zone.zone_id) is not None
        and ensure_utc(first_episode[zone.zone_id].touch_at).year == int(target_year)
    ]
    h4_episodes.sort(key=lambda row: (row.touch_at, row.zone_id))
    zone_by_id = {zone.zone_id: zone for zone in zones}

    m5_frame = _resample_ohlc(price, "5min")
    m5_bars = _bars_from_frame(m5_frame, "M5")

    hierarchy = _historical_hierarchy(history_details)
    children: list[dict[str, Any]] = []
    parents: list[dict[str, Any]] = []
    reject = Counter()

    for episode in h4_episodes:
        parent_zone = zone_by_id.get(str(episode.zone_id))
        if parent_zone is None:
            reject["PARENT_ZONE_MISSING"] += 1
            continue
        touch_at = ensure_utc(episode.touch_at)
        previous = _latest_close_before(price, touch_at)
        if previous is None:
            reject["NO_DECISION_PRICE"] += 1
            continue
        decision_at, decision_price = previous

        htf, m15 = _active_zone_dicts(
            zones,
            as_of=decision_at,
            first_touch_by_zone=first_touch_at,
            invalidated_by_zone=invalidated,
            superseded_by_zone=superseded,
        )
        dmap = _direction_map(
            direction=str(episode.direction),
            price=float(decision_price),
            atlas_zones=htf,
            m15_zones=m15,
            history_details=history_details,
            hierarchy=hierarchy,
        )
        if _selected_h4_id(dmap) != parent_zone.zone_id:
            reject["NOT_NEAREST_FRESH_H4_AT_DECISION"] += 1
            continue

        candidate = dict(dmap.get("depth_entry_candidate") or {})
        ladder = dict(dmap.get("four_order_ladder") or {})
        if not bool(candidate.get("calibrated_fresh_first_touch")):
            reject["NOT_CALIBRATED_FRESH"] += 1
            continue
        slots = [dict(x) for x in list(ladder.get("slots") or [])]
        if len(slots) != 4:
            reject["NO_FOUR_SLOT_LADDER"] += 1
            continue

        h4_dict = dict(dict(dmap.get("h4") or {}).get("zone") or {})
        h1_dict = dict(dict(dmap.get("h1") or {}).get("zone") or {})
        h4_low = _f(h4_dict.get("low"))
        h4_high = _f(h4_dict.get("high"))
        h4_atr = _f(h4_dict.get("atr_points"))
        if h4_low is None or h4_high is None or h4_atr is None or h4_atr <= 0:
            reject["H4_STOP_GEOMETRY_MISSING"] += 1
            continue
        direction = str(episode.direction)
        stop = (
            h4_low - STOP_BUFFER_ATR * h4_atr
            if direction == "LONG"
            else h4_high + STOP_BUFFER_ATR * h4_atr
        )
        cancel_at = _parent_cancel_at(
            decision_at=decision_at,
            invalidated_at=invalidated.get(parent_zone.zone_id),
            superseded_at=superseded.get(parent_zone.zone_id),
        )
        source_layer = str(candidate.get("source_layer") or "")

        parent_record = {
            "year": int(target_year),
            "parent_zone_id": parent_zone.zone_id,
            "direction": direction,
            "decision_at": decision_at.isoformat(),
            "touch_at": touch_at.isoformat(),
            "decision_price": float(decision_price),
            "source_layer": source_layer,
            "entry_low": _f(candidate.get("entry_low")),
            "entry_high": _f(candidate.get("entry_high")),
            "stop": float(stop),
            "cancel_at": cancel_at.isoformat(),
            "h1_source_zone_id": h1_dict.get("zone_id"),
            "selected_h4_mode": dmap.get("h4_selection_mode"),
            "prior_mode": "FROZEN_FULL_2012_2026_RETROSPECTIVE",
        }
        parents.append(parent_record)

        for raw_slot in slots:
            slot = int(raw_slot.get("slot") or 0)
            stage = str(raw_slot.get("stage") or "")
            if slot <= 2:
                entry = _f(raw_slot.get("reference_price"))
                activated_at = decision_at
                activation = "PRE_TOUCH_LIMIT"
                if entry is None or not _limit_side_valid(direction, entry, decision_price):
                    child = _child_result(
                        year=target_year,
                        parent_zone_id=parent_zone.zone_id,
                        direction=direction,
                        source_layer=source_layer,
                        slot=slot,
                        stage=stage,
                        activation="INVALID_LIMIT_SIDE_AT_PLAN",
                        activated_at=None,
                        entry=entry,
                        stop=stop,
                        target=None,
                        target_timeframe=None,
                        target_zone_id=None,
                        px_index=px_index,
                        cancel_at=cancel_at,
                    )
                    children.append(_serialize_child(child))
                    continue
            else:
                activation_row = _m5_activation(
                    slot=slot,
                    direction=direction,
                    h1_source=h1_dict,
                    h4_parent=h4_dict,
                    m5_bars=m5_bars,
                    start_at=touch_at,
                    cancel_at=cancel_at,
                )
                if activation_row is None:
                    child = _child_result(
                        year=target_year,
                        parent_zone_id=parent_zone.zone_id,
                        direction=direction,
                        source_layer=source_layer,
                        slot=slot,
                        stage=stage,
                        activation="M5_CONFIRMATION_NOT_AVAILABLE",
                        activated_at=None,
                        entry=None,
                        stop=stop,
                        target=None,
                        target_timeframe=None,
                        target_zone_id=None,
                        px_index=px_index,
                        cancel_at=cancel_at,
                    )
                    children.append(_serialize_child(child))
                    continue
                activated_at, entry, activation = activation_row

            target_htf, target_m15 = _active_zone_dicts(
                zones,
                as_of=activated_at,
                first_touch_by_zone=first_touch_at,
                invalidated_by_zone=invalidated,
                superseded_by_zone=superseded,
            )
            target, target_tf, target_zone_id, target_plan = _target_for_slot(
                slot=slot,
                direction=direction,
                entry=float(entry),
                stop=float(stop),
                htf_zones=target_htf,
                m15_zones=target_m15,
            )
            if target is None or not bool(target_plan.get("terminal_rr_eligible")):
                child = _child_result(
                    year=target_year,
                    parent_zone_id=parent_zone.zone_id,
                    direction=direction,
                    source_layer=source_layer,
                    slot=slot,
                    stage=stage,
                    activation="NO_VALID_STRUCTURAL_TARGET",
                    activated_at=None,
                    entry=float(entry),
                    stop=stop,
                    target=None,
                    target_timeframe=None,
                    target_zone_id=None,
                    px_index=px_index,
                    cancel_at=cancel_at,
                )
                children.append(_serialize_child(child))
                continue

            child = _child_result(
                year=target_year,
                parent_zone_id=parent_zone.zone_id,
                direction=direction,
                source_layer=source_layer,
                slot=slot,
                stage=stage,
                activation=activation,
                activated_at=activated_at,
                entry=float(entry),
                stop=stop,
                target=float(target),
                target_timeframe=target_tf,
                target_zone_id=target_zone_id,
                px_index=px_index,
                cancel_at=cancel_at,
            )
            children.append(_serialize_child(child))

    summary = summarize_children(children, parents=parents)
    summary["h4_first_touch_opportunities"] = len(h4_episodes)
    summary["rejections"] = dict(reject)
    summary["zone_count"] = len(zones)
    summary["prior_mode"] = "FROZEN_FULL_2012_2026_RETROSPECTIVE"
    summary["same_bar_precedence"] = SAME_BAR_PRECEDENCE
    summary["max_position_hold_hours"] = MAX_POSITION_HOLD_HOURS
    return summary, parents, children


def summarize_children(
    children: Sequence[dict[str, Any]],
    *,
    parents: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rows = [dict(x) for x in children]
    filled = [r for r in rows if r.get("filled_at")]
    closed = [r for r in filled if r.get("pnl_points") is not None]
    tps = [r for r in closed if r.get("outcome") == "TP"]
    sls = [r for r in closed if r.get("outcome") == "SL"]
    time_exits = [r for r in closed if str(r.get("outcome") or "").startswith("TIME_EXIT")]
    censored = [r for r in closed if r.get("outcome") == "CENSORED_DATA_END"]
    pnl = [float(r["pnl_points"]) for r in closed]
    rs = [float(r["r_multiple"]) for r in closed if r.get("r_multiple") is not None]
    gross_profit = sum(x for x in pnl if x > 0)
    gross_loss = -sum(x for x in pnl if x < 0)

    ordered = sorted(
        closed,
        key=lambda r: str(r.get("exit_at") or ""),
    )
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    losses = 0
    max_loss_streak = 0
    for row in ordered:
        value = float(row.get("pnl_points") or 0.0)
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if value < 0:
            losses += 1
            max_loss_streak = max(max_loss_streak, losses)
        else:
            losses = 0

    slot_metrics: dict[str, Any] = {}
    for slot in range(1, 5):
        slot_rows = [r for r in rows if int(r.get("slot") or 0) == slot]
        slot_filled = [r for r in slot_rows if r.get("filled_at")]
        slot_closed = [r for r in slot_filled if r.get("pnl_points") is not None]
        slot_metrics[str(slot)] = {
            "planned": len(slot_rows),
            "activated": sum(r.get("activated_at") is not None for r in slot_rows),
            "filled": len(slot_filled),
            "fill_rate": None if not slot_rows else len(slot_filled) / len(slot_rows),
            "tp": sum(r.get("outcome") == "TP" for r in slot_closed),
            "sl": sum(r.get("outcome") == "SL" for r in slot_closed),
            "gross_pnl_points": sum(float(r.get("pnl_points") or 0.0) for r in slot_closed),
            "mean_r": None if not slot_closed else mean(
                float(r.get("r_multiple") or 0.0) for r in slot_closed
            ),
        }

    source_counts = Counter(str(p.get("source_layer") or "UNKNOWN") for p in parents)
    target_counts = Counter(str(r.get("target_timeframe") or "NONE") for r in rows)
    return {
        "parents": len(parents),
        "children_planned": len(rows),
        "children_activated": sum(r.get("activated_at") is not None for r in rows),
        "children_filled": len(filled),
        "child_fill_rate": None if not rows else len(filled) / len(rows),
        "closed_children": len(closed),
        "tp": len(tps),
        "sl": len(sls),
        "time_exit_30d": len(time_exits),
        "censored_data_end": len(censored),
        "tp_rate_of_filled": None if not filled else len(tps) / len(filled),
        "gross_pnl_points": sum(pnl),
        "gross_pnl_usd_001": sum(pnl) * OZ_PER_001_LOT,
        "gross_profit_points": gross_profit,
        "gross_loss_points": gross_loss,
        "profit_factor": None if gross_loss <= 0 else gross_profit / gross_loss,
        "mean_r": None if not rs else mean(rs),
        "median_r": None if not rs else float(np.median(np.array(rs, dtype=float))),
        "max_drawdown_points_realized_sequence": max_dd,
        "max_consecutive_losses": max_loss_streak,
        "source_layer_counts": dict(source_counts),
        "target_timeframe_counts": dict(target_counts),
        "slot_metrics": slot_metrics,
        "cost_stress": {
            str(cost): {
                "net_pnl_usd_001": sum(pnl) * OZ_PER_001_LOT - len(filled) * cost,
                "assumed_round_trip_cost_usd_per_001": cost,
            }
            for cost in (0.0, 0.30, 0.50, 1.00)
        },
        "lot_assumption": {
            "lot_per_child": CHILD_LOT,
            "oz_per_001_lot": OZ_PER_001_LOT,
            "usd_pnl_per_1_price_point_per_child": OZ_PER_001_LOT,
        },
    }


def summarize_group(children: Sequence[dict[str, Any]], parents: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return summarize_children(children, parents=parents)


def load_price_frame(path: str) -> pd.DataFrame:
    return _load_price_frame(path)

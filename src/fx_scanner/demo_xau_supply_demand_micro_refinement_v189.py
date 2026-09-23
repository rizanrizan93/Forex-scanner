from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc

CONTRACT = "XAU_SUPPLY_DEMAND_M5_MICRO_REFINEMENT_V189"
MAX_RECENT_M5_BARS = 144
SWING_LOOKBACK_BARS = 36
MSS_FALLBACK_LOOKBACK = 6
ATR_PERIOD = 14
DISPLACEMENT_BODY_ATR = 0.50
DISPLACEMENT_RANGE_ATR = 0.80
DISPLACEMENT_CLOSE_LOCATION = 0.70


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _completed_m5(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(bars), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=5) <= now
    )


def _atr_at(rows: Sequence[Bar], index: int, period: int = ATR_PERIOD) -> float | None:
    if index < 1:
        return None
    start = max(1, index - int(period) + 1)
    values: list[float] = []
    for i in range(start, index + 1):
        row = rows[i]
        prev_close = float(rows[i - 1].close)
        tr = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - prev_close),
            abs(float(row.low) - prev_close),
        )
        values.append(tr)
    if not values:
        return None
    atr = sum(values) / len(values)
    return atr if atr > 0 and isfinite(atr) else None


def _touches_source(row: Bar, source: dict[str, Any]) -> bool:
    low = _safe_float(source.get("low"))
    high = _safe_float(source.get("high"))
    if low is None or high is None:
        return False
    return float(row.high) >= low and float(row.low) <= high


def _source_invalidated(row: Bar, source: dict[str, Any], direction: str) -> bool:
    distal = _safe_float(source.get("distal"))
    if distal is None:
        return False
    if direction == "LONG":
        return float(row.close) < distal
    return float(row.close) > distal


def _latest_pre_sweep_swing_level(
    rows: Sequence[Bar],
    *,
    sweep_index: int,
    direction: str,
) -> tuple[float | None, str]:
    start = max(2, sweep_index - SWING_LOOKBACK_BARS)
    end = max(start, sweep_index - 2)
    swings: list[tuple[int, float]] = []
    for i in range(start, end + 1):
        if i + 2 >= sweep_index:
            break
        if direction == "LONG":
            center = float(rows[i].high)
            if (
                center > float(rows[i - 1].high)
                and center >= float(rows[i - 2].high)
                and center > float(rows[i + 1].high)
                and center >= float(rows[i + 2].high)
            ):
                swings.append((i, center))
        else:
            center = float(rows[i].low)
            if (
                center < float(rows[i - 1].low)
                and center <= float(rows[i - 2].low)
                and center < float(rows[i + 1].low)
                and center <= float(rows[i + 2].low)
            ):
                swings.append((i, center))
    if swings:
        return swings[-1][1], "PRE_SWEEP_CONFIRMED_M5_SWING"

    prior = rows[max(0, sweep_index - MSS_FALLBACK_LOOKBACK):sweep_index]
    if not prior:
        return None, "NO_MSS_REFERENCE"
    if direction == "LONG":
        return max(float(row.high) for row in prior), "PRE_SWEEP_M5_RANGE_FALLBACK"
    return min(float(row.low) for row in prior), "PRE_SWEEP_M5_RANGE_FALLBACK"


def _candidate_pocket_from_bar(row: Bar, direction: str) -> dict[str, Any]:
    if direction == "LONG":
        low = float(row.low)
        high = max(float(row.open), float(row.close))
    else:
        low = min(float(row.open), float(row.close))
        high = float(row.high)
    if high <= low:
        low, high = min(float(row.low), float(row.high)), max(float(row.low), float(row.high))
    return {
        "low": low,
        "high": high,
        "source": "M5_SWEEP_ORIGIN_CANDIDATE",
    }


def _confirmed_origin_pocket(
    rows: Sequence[Bar],
    *,
    sweep_index: int,
    trigger_index: int,
    direction: str,
) -> dict[str, Any]:
    candidates: list[tuple[int, Bar]] = []
    for i in range(sweep_index, trigger_index + 1):
        row = rows[i]
        if direction == "LONG" and float(row.close) < float(row.open):
            candidates.append((i, row))
        elif direction == "SHORT" and float(row.close) > float(row.open):
            candidates.append((i, row))
    origin_index, origin = candidates[-1] if candidates else (sweep_index, rows[sweep_index])
    pocket = _candidate_pocket_from_bar(origin, direction)
    pocket.update(
        {
            "source": "LAST_OPPOSITE_M5_CANDLE_BEFORE_DISPLACEMENT",
            "origin_at": ensure_utc(origin.timestamp).isoformat(),
            "origin_index": int(origin_index),
        }
    )
    return pocket


def evaluate_micro_refinement(
    m5_bars: Sequence[Bar],
    *,
    path_map: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    active_path = dict(path_map.get("active_path") or {})
    source = dict(active_path.get("source_zone") or {})
    direction = str(active_path.get("reaction_direction") or "").upper()
    base = {
        "contract": CONTRACT,
        "policy_effect": "SHADOW_PREPARE_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "direction": direction or None,
        "source_zone_id": source.get("zone_id"),
        "source_timeframe": source.get("timeframe"),
    }
    if direction not in {"LONG", "SHORT"} or not source:
        return base | {"state": "NO_ACTIVE_REACTION_PATH"}
    if str(source.get("timeframe") or "").upper() != "H1":
        return base | {
            "state": "WAIT_H1_PRECISION_SOURCE",
            "note": "M5 refinement only refines an H1 precision source; H4/D1 remain parent context.",
        }

    rows = _completed_m5(m5_bars, as_of=as_of)
    if len(rows) < 40:
        return base | {"state": "INSUFFICIENT_M5_HISTORY"}

    recent = rows[-MAX_RECENT_M5_BARS:]
    global_offset = len(rows) - len(recent)
    touch_indices = [i for i, row in enumerate(recent) if _touches_source(row, source)]
    if not touch_indices:
        return base | {
            "state": "WAIT_SOURCE_TOUCH",
            "last_closed_m5_price": float(recent[-1].close),
        }

    # Use the deepest directional excursion among recent source-touch bars as the
    # micro sweep candidate. This remains descriptive until reclaim/MSS/displacement.
    if direction == "LONG":
        sweep_index = min(touch_indices, key=lambda i: float(recent[i].low))
        sweep_price = float(recent[sweep_index].low)
    else:
        sweep_index = max(touch_indices, key=lambda i: float(recent[i].high))
        sweep_price = float(recent[sweep_index].high)
    sweep_bar = recent[sweep_index]

    source_proximal = _safe_float(source.get("proximal"))
    if source_proximal is None:
        source_proximal = (
            _safe_float(source.get("high"))
            if direction == "LONG"
            else _safe_float(source.get("low"))
        )
    mss_level, mss_basis = _latest_pre_sweep_swing_level(
        recent,
        sweep_index=sweep_index,
        direction=direction,
    )

    post = recent[sweep_index:]
    reclaim_index: int | None = None
    if source_proximal is not None:
        for local_i, row in enumerate(post, start=sweep_index):
            if direction == "LONG" and float(row.close) >= source_proximal:
                reclaim_index = local_i
                break
            if direction == "SHORT" and float(row.close) <= source_proximal:
                reclaim_index = local_i
                break

    mss_index: int | None = None
    if reclaim_index is not None and mss_level is not None:
        for i in range(reclaim_index, len(recent)):
            close = float(recent[i].close)
            if direction == "LONG" and close > mss_level:
                mss_index = i
                break
            if direction == "SHORT" and close < mss_level:
                mss_index = i
                break

    displacement_index: int | None = None
    if mss_index is not None:
        for i in range(mss_index, len(recent)):
            row = recent[i]
            atr = _atr_at(recent, i)
            if atr is None:
                continue
            rng = float(row.high) - float(row.low)
            body = abs(float(row.close) - float(row.open))
            if rng <= 0:
                continue
            if direction == "LONG":
                directional = float(row.close) > float(row.open)
                close_location = (float(row.close) - float(row.low)) / rng
                beyond_mss = mss_level is not None and float(row.close) > mss_level
            else:
                directional = float(row.close) < float(row.open)
                close_location = (float(row.high) - float(row.close)) / rng
                beyond_mss = mss_level is not None and float(row.close) < mss_level
            if (
                directional
                and beyond_mss
                and body >= DISPLACEMENT_BODY_ATR * atr
                and rng >= DISPLACEMENT_RANGE_ATR * atr
                and close_location >= DISPLACEMENT_CLOSE_LOCATION
            ):
                displacement_index = i
                break

    invalidated = any(
        _source_invalidated(row, source, direction)
        for row in recent[sweep_index:]
    )
    candidate_pocket = _candidate_pocket_from_bar(sweep_bar, direction)
    candidate_pocket["origin_at"] = ensure_utc(sweep_bar.timestamp).isoformat()

    if invalidated:
        state = "SOURCE_INVALIDATED_NO_REFINEMENT"
    elif reclaim_index is None:
        state = "M5_TOUCH_WAIT_RECLAIM"
    elif mss_index is None:
        state = "M5_RECLAIM_WAIT_MSS"
    elif displacement_index is None:
        state = "M5_MSS_WAIT_DISPLACEMENT"
    else:
        state = "M5_REFINEMENT_CONFIRMED_SHADOW"

    refined_pocket = None
    if displacement_index is not None and not invalidated:
        refined_pocket = _confirmed_origin_pocket(
            recent,
            sweep_index=sweep_index,
            trigger_index=displacement_index,
            direction=direction,
        )

    return base | {
        "state": state,
        "last_closed_m5_price": float(recent[-1].close),
        "sweep": {
            "price": sweep_price,
            "at": ensure_utc(sweep_bar.timestamp).isoformat(),
            "source": "DEEPEST_RECENT_M5_SOURCE_TOUCH",
        },
        "source_proximal_reclaim_level": source_proximal,
        "reclaim_confirmed": reclaim_index is not None,
        "reclaim_at": (
            None
            if reclaim_index is None
            else ensure_utc(recent[reclaim_index].timestamp).isoformat()
        ),
        "mss_level": mss_level,
        "mss_basis": mss_basis,
        "mss_confirmed": mss_index is not None,
        "mss_at": (
            None
            if mss_index is None
            else ensure_utc(recent[mss_index].timestamp).isoformat()
        ),
        "displacement_confirmed": displacement_index is not None,
        "displacement_at": (
            None
            if displacement_index is None
            else ensure_utc(recent[displacement_index].timestamp).isoformat()
        ),
        "candidate_entry_pocket": candidate_pocket,
        "refined_entry_pocket": refined_pocket,
        "required_for_execution": False,
        "interpretation": (
            "Micro pocket is preparation evidence only. Canonical AFIC and completed "
            "M15 confirmation remain required for execution admission."
        ),
        "bars_considered": len(recent),
        "global_sweep_index": global_offset + sweep_index,
    }

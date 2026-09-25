from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc

CONTRACT = "XAU_SUPPLY_DEMAND_M5_MICRO_REFINEMENT_V189"
MAX_RECENT_M5_BARS = 144
SWING_LOOKBACK_BARS = 36
MSS_FALLBACK_LOOKBACK = 6
LOCAL_MSS_LOOKBACK_BARS = 12
LOCAL_MSS_FALLBACK_LOOKBACK = 6
ATR_PERIOD = 14
DISPLACEMENT_BODY_ATR = 0.50
DISPLACEMENT_RANGE_ATR = 0.80
DISPLACEMENT_CLOSE_LOCATION = 0.70
PARENT_REVERSAL_RESCUE_MAX_ATR = 0.35


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _safe_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
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
    return ensure_utc(parsed)


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


def _latest_local_pre_sweep_mss_level(
    rows: Sequence[Bar],
    *,
    sweep_index: int,
    first_touch_index: int,
    direction: str,
) -> tuple[float | None, str, int | None]:
    """Return a source-local internal MSS reference.

    V189 originally used only the conservative 2-left/2-right pre-sweep swing.
    During a near-vertical approach that level can sit near the far end of the
    projected reaction path, so confirmation arrives after most of the move is
    already complete. The local reference is intentionally narrower:

    * it can only come from bars after the H1 source was first touched;
    * it uses a 1-left/1-right internal M5 pivot for executable micro structure;
    * if no pivot exists, it falls back to the recent post-touch range;
    * the older conservative structural MSS is still computed and reported
      separately by evaluate_micro_refinement.

    This remains shadow/preparation evidence and does not grant execution
    authority.
    """
    if sweep_index <= 1 or first_touch_index >= sweep_index:
        return None, "NO_LOCAL_MSS_REFERENCE", None

    start = max(
        1,
        int(first_touch_index),
        int(sweep_index) - LOCAL_MSS_LOOKBACK_BARS,
    )
    end = int(sweep_index) - 1
    swings: list[tuple[int, float]] = []
    for i in range(start, end):
        # A local pivot must be confirmed by the next completed M5 bar and must
        # remain strictly pre-sweep.
        if i + 1 >= sweep_index:
            break
        if direction == "LONG":
            center = float(rows[i].high)
            if (
                center > float(rows[i - 1].high)
                and center >= float(rows[i + 1].high)
            ):
                swings.append((i, center))
        else:
            center = float(rows[i].low)
            if (
                center < float(rows[i - 1].low)
                and center <= float(rows[i + 1].low)
            ):
                swings.append((i, center))

    if swings:
        index, level = swings[-1]
        return level, "POST_SOURCE_TOUCH_INTERNAL_M5_SWING", index

    fallback_start = max(
        int(first_touch_index),
        int(sweep_index) - LOCAL_MSS_FALLBACK_LOOKBACK,
    )
    if fallback_start >= sweep_index:
        return None, "NO_LOCAL_MSS_REFERENCE", None

    indices = list(range(fallback_start, sweep_index))
    if not indices:
        return None, "NO_LOCAL_MSS_REFERENCE", None
    if direction == "LONG":
        level = max(float(rows[i].high) for i in indices)
        index = max(i for i in indices if float(rows[i].high) == level)
    else:
        level = min(float(rows[i].low) for i in indices)
        index = max(i for i in indices if float(rows[i].low) == level)
    return level, "POST_SOURCE_TOUCH_M5_RANGE_FALLBACK", index


def _first_close_break_index(
    rows: Sequence[Bar],
    *,
    start_index: int,
    direction: str,
    level: float | None,
) -> int | None:
    if level is None:
        return None
    for i in range(int(start_index), len(rows)):
        close = float(rows[i].close)
        if direction == "LONG" and close > float(level):
            return i
        if direction == "SHORT" and close < float(level):
            return i
    return None


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
    parent_source_zone: dict[str, Any] | None = None,
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
        "source_available_at": source.get("available_at"),
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

    source_available_at = _safe_datetime(source.get("available_at"))
    if source_available_at is None:
        return base | {
            "state": "SOURCE_AVAILABILITY_UNKNOWN_NO_REFINEMENT",
            "note": (
                "Fail-closed: M5 refinement requires the H1 source available_at timestamp "
                "so pre-source historical touches cannot be reused retrospectively."
            ),
        }

    recent = rows[-MAX_RECENT_M5_BARS:]
    global_offset = len(rows) - len(recent)
    pre_source_touch_count = sum(
        1
        for row in recent
        if ensure_utc(row.timestamp) < source_available_at
        and _touches_source(row, source)
    )
    touch_indices = [
        i
        for i, row in enumerate(recent)
        if ensure_utc(row.timestamp) >= source_available_at
        and _touches_source(row, source)
    ]
    if not touch_indices:
        return base | {
            "state": "WAIT_SOURCE_TOUCH",
            "last_closed_m5_price": float(recent[-1].close),
            "source_available_at": source_available_at.isoformat(),
            "pre_source_touch_count_ignored": pre_source_touch_count,
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
    structural_mss_level, structural_mss_basis = _latest_pre_sweep_swing_level(
        recent,
        sweep_index=sweep_index,
        direction=direction,
    )
    local_mss_level, local_mss_basis, local_mss_reference_index = (
        _latest_local_pre_sweep_mss_level(
            recent,
            sweep_index=sweep_index,
            first_touch_index=touch_indices[0],
            direction=direction,
        )
    )
    if local_mss_level is not None:
        mss_level = local_mss_level
        mss_basis = local_mss_basis
        mss_scope = "LOCAL_EXECUTABLE"
    else:
        mss_level = structural_mss_level
        mss_basis = structural_mss_basis
        mss_scope = "STRUCTURAL_FALLBACK"

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
    structural_mss_index: int | None = None
    if reclaim_index is not None:
        mss_index = _first_close_break_index(
            recent,
            start_index=reclaim_index,
            direction=direction,
            level=mss_level,
        )
        structural_mss_index = _first_close_break_index(
            recent,
            start_index=reclaim_index,
            direction=direction,
            level=structural_mss_level,
        )

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

    # V219: an H1 child break is not sufficient to erase real M5 reversal
    # evidence when that break occurs *inside* a still-valid overlapping HTF
    # parent. In that context the H1 invalidation may itself be the liquidity
    # sweep that starts the H4/D1 reaction. Preserve the candidate immediately
    # (shadow/prepare only) and let reclaim/MSS/displacement progressively
    # refine it. Parent invalidation still retires the rescue path.
    parent = dict(parent_source_zone or {})
    parent_rescue = False
    parent_rescue_mode = None
    parent_penetration_atr = None
    parent_contains_sweep = False
    if invalidated and parent:
        parent_low = _safe_float(parent.get("low"))
        parent_high = _safe_float(parent.get("high"))
        parent_distal = _safe_float(parent.get("distal"))
        child_low = _safe_float(source.get("low"))
        child_high = _safe_float(source.get("high"))
        child_distal = _safe_float(source.get("distal"))
        sweep_atr = _atr_at(recent, sweep_index)
        same_direction = str(parent.get("direction") or direction).upper() == direction
        overlaps_child = (
            None not in {parent_low, parent_high, child_low, child_high}
            and child_low <= parent_high and child_high >= parent_low
        )
        parent_active = dict(parent.get("lifecycle") or {}).get("active", True) is not False
        parent_not_invalidated = not any(
            _source_invalidated(row, parent, direction)
            for row in recent[sweep_index:]
        )
        sweep_extreme = (
            float(sweep_bar.low) if direction == "LONG" else float(sweep_bar.high)
        )
        parent_contains_sweep = bool(
            parent_low is not None
            and parent_high is not None
            and parent_low <= sweep_extreme <= parent_high
        )
        if child_distal is not None and sweep_atr:
            excursion = (
                max(0.0, child_distal - float(sweep_bar.low))
                if direction == "LONG"
                else max(0.0, float(sweep_bar.high) - child_distal)
            )
            parent_penetration_atr = excursion / sweep_atr

        marginal_child_break = bool(
            parent_penetration_atr is not None
            and parent_penetration_atr <= PARENT_REVERSAL_RESCUE_MAX_ATR
        )
        micro_reversal_visible = bool(
            reclaim_index is not None
            or mss_index is not None
            or displacement_index is not None
        )
        if (
            same_direction
            and overlaps_child
            and parent_active
            and parent_not_invalidated
            and parent_distal is not None
            and parent_contains_sweep
        ):
            invalidated = False
            parent_rescue = True
            if micro_reversal_visible:
                parent_rescue_mode = "HTF_PARENT_WITH_LIVE_M5_REVERSAL"
            elif marginal_child_break:
                parent_rescue_mode = "HTF_PARENT_MARGINAL_CHILD_BREAK"
            else:
                parent_rescue_mode = "HTF_PARENT_OWNS_SWEEP_WAIT_CONFIRMATION"

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
        "source_available_at": source_available_at.isoformat(),
        "pre_source_touch_count_ignored": pre_source_touch_count,
        "first_eligible_touch_at": ensure_utc(recent[touch_indices[0]].timestamp).isoformat(),
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
        "mss_scope": mss_scope,
        "local_mss_level": local_mss_level,
        "local_mss_basis": local_mss_basis,
        "local_mss_reference_at": (
            None
            if local_mss_reference_index is None
            else ensure_utc(recent[local_mss_reference_index].timestamp).isoformat()
        ),
        "structural_mss_level": structural_mss_level,
        "structural_mss_basis": structural_mss_basis,
        "mss_confirmed": mss_index is not None,
        "mss_at": (
            None
            if mss_index is None
            else ensure_utc(recent[mss_index].timestamp).isoformat()
        ),
        "structural_mss_confirmed": structural_mss_index is not None,
        "structural_mss_at": (
            None
            if structural_mss_index is None
            else ensure_utc(recent[structural_mss_index].timestamp).isoformat()
        ),
        "displacement_confirmed": displacement_index is not None,
        "displacement_at": (
            None
            if displacement_index is None
            else ensure_utc(recent[displacement_index].timestamp).isoformat()
        ),
        "candidate_entry_pocket": candidate_pocket,
        "refined_entry_pocket": refined_pocket,
        "parent_reversal_rescue": {
            "active": parent_rescue,
            "mode": parent_rescue_mode,
            "parent_zone_id": parent.get("zone_id") if parent_rescue else None,
            "parent_timeframe": parent.get("timeframe") if parent_rescue else None,
            "parent_contains_sweep": parent_contains_sweep,
            "child_penetration_atr": (
                None
                if parent_penetration_atr is None
                else round(parent_penetration_atr, 4)
            ),
            "marginal_reference_atr": PARENT_REVERSAL_RESCUE_MAX_ATR,
            "reclaim_visible": reclaim_index is not None,
            "mss_visible": mss_index is not None,
            "displacement_visible": displacement_index is not None,
            "effect": "SHADOW_PREPARE_ONLY",
        },
        "required_for_execution": False,
        "interpretation": (
            "V189 uses post-source-touch local M5 structure for the executable micro MSS "
            "while preserving the older conservative pre-sweep structural MSS separately. "
            "Micro pocket remains preparation evidence only; canonical AFIC and completed "
            "M15 confirmation remain required for execution admission."
        ),
        "bars_considered": len(recent),
        "global_sweep_index": global_offset + sweep_index,
    }

from __future__ import annotations

import json
import os
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_nested_m5_v228 import (
    M5_ACTIVE_HOURS,
    _active_at as _m5_active_at,
    _detect_m5_zones,
    _first_invalidation_map,
    _m5_superseded_at,
)
from .research_xau_zone_reversal_depth_v225 import (
    OBSERVATION_HOURS,
    PriceIndex,
    _active_at,
    _first_invalidation_at,
    _load_price_frame,
    _price_index,
    _resample_ohlc,
    build_zones,
    causal_superseded_at,
    evaluate_first_touch,
)

RESEARCH_VERSION = "XAU_H4_H1_SD_M15_M5_CONTINUATION_V234_1"
ARTIFACT_CONTRACT = "XAU_H4_H1_SD_M15_M5_CONTINUATION_YEAR_V234_1"

ENTRY_HORIZON_HOURS = 8
MAX_HOLD_HOURS = 16
STOP_BUFFER_ATR = 0.15
FIXED_R_TARGET = 2.0
MIN_TERMINAL_RR = 1.0

TARGET_POLICIES = ("R2", "H1_TERMINAL")


def _year() -> int:
    year = int(os.getenv("XAU_V234_YEAR", "0") or 0)
    if year < 2012 or year > 2026:
        raise SystemExit(f"XAU_V234_YEAR_INVALID:{year}")
    return year


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _h4_context(price: pd.DataFrame) -> pd.DataFrame:
    h4 = _resample_ohlc(price, "4h").copy()
    h4["ema20"] = _ema(h4["close"], 20)
    h4["ema50"] = _ema(h4["close"], 50)
    h4["ema200"] = _ema(h4["close"], 200)
    h4["close_at"] = pd.to_datetime(h4["time"], utc=True) + pd.Timedelta(hours=4)
    h4["direction"] = "NEUTRAL"
    long_mask = (
        (h4["ema20"] > h4["ema50"])
        & (h4["ema50"] > h4["ema200"])
        & (h4["close"] > h4["ema20"])
        & (h4["ema20"] > h4["ema20"].shift(2))
    )
    short_mask = (
        (h4["ema20"] < h4["ema50"])
        & (h4["ema50"] < h4["ema200"])
        & (h4["close"] < h4["ema20"])
        & (h4["ema20"] < h4["ema20"].shift(2))
    )
    h4.loc[long_mask, "direction"] = "LONG"
    h4.loc[short_mask, "direction"] = "SHORT"
    return h4


def _h4_direction_at(h4: pd.DataFrame, at: datetime) -> str:
    closes = h4["close_at"].to_numpy(dtype="datetime64[ns]")
    point = np.datetime64(pd.Timestamp(at).to_datetime64())
    idx = int(np.searchsorted(closes, point, side="right")) - 1
    if idx < 0:
        return "NEUTRAL"
    return str(h4.iloc[idx]["direction"])


def _overlap_fraction(child: Any, parent: Any) -> float:
    overlap = max(
        0.0,
        min(float(child.high), float(parent.high))
        - max(float(child.low), float(parent.low)),
    )
    width = max(float(child.high) - float(child.low), 1e-12)
    return overlap / width


def _width(zone: Any) -> float:
    return max(float(zone.high) - float(zone.low), 1e-12)


def _nested_rank(zone: Any, parent: Any) -> tuple[float, float, float]:
    return (
        -_overlap_fraction(zone, parent),
        _width(zone),
        -ensure_utc(zone.available_at).timestamp(),
    )


def _valid_until_m5(
    zone: Any,
    *,
    superseded: dict[str, datetime | None],
    invalidated: dict[str, datetime | None],
    touch_at: datetime,
) -> datetime:
    candidates = [
        ensure_utc(touch_at) + timedelta(hours=ENTRY_HORIZON_HOURS),
        ensure_utc(zone.available_at) + timedelta(hours=M5_ACTIVE_HOURS),
    ]
    if superseded.get(zone.zone_id) is not None:
        candidates.append(ensure_utc(superseded[zone.zone_id]))
    if invalidated.get(zone.zone_id) is not None:
        candidates.append(ensure_utc(invalidated[zone.zone_id]))
    return min(candidates)


def _terminal_h1_target(
    h1_zones: Sequence[Any],
    *,
    direction: str,
    entry: float,
    at: datetime,
    invalidated: dict[str, datetime | None],
    superseded: dict[str, datetime | None],
) -> tuple[float | None, str | None]:
    opposite = "SHORT" if direction == "LONG" else "LONG"
    candidates = []
    for zone in h1_zones:
        if zone.direction != opposite:
            continue
        if ensure_utc(zone.available_at) >= ensure_utc(at):
            continue
        if not _active_at(zone, invalidated, superseded, at):
            continue
        target = float(zone.low) if direction == "LONG" else float(zone.high)
        if direction == "LONG" and target <= entry:
            continue
        if direction == "SHORT" and target >= entry:
            continue
        candidates.append((abs(target - entry), target, zone.zone_id))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, target, zone_id = candidates[0]
    return float(target), str(zone_id)


def _find_fill(
    price: pd.DataFrame,
    *,
    level: float,
    start_at: datetime,
    valid_until: datetime,
) -> tuple[int | None, datetime | None]:
    timestamps = tuple(pd.Timestamp(v) for v in price["timestamp"])
    start = bisect_left(timestamps, pd.Timestamp(ensure_utc(start_at)))
    end = bisect_left(timestamps, pd.Timestamp(ensure_utc(valid_until)))
    if end <= start:
        return None, None
    highs = price["high"].to_numpy(dtype=float, copy=False)
    lows = price["low"].to_numpy(dtype=float, copy=False)
    mask = (lows[start:end] <= level) & (highs[start:end] >= level)
    hits = np.flatnonzero(mask)
    if len(hits) == 0:
        return None, None
    idx = start + int(hits[0])
    return idx, ensure_utc(timestamps[idx].to_pydatetime())


def _resolve(
    price: pd.DataFrame,
    *,
    fill_index: int,
    fill_at: datetime,
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    timestamps = tuple(pd.Timestamp(v) for v in price["timestamp"])
    deadline = ensure_utc(fill_at) + timedelta(hours=MAX_HOLD_HOURS)
    end = bisect_right(timestamps, pd.Timestamp(deadline))
    end = min(end, len(price))
    for idx in range(fill_index, end):
        row = price.iloc[idx]
        if direction == "LONG":
            sl_hit = float(row["low"]) <= stop
            tp_hit = float(row["high"]) >= target
        else:
            sl_hit = float(row["high"]) >= stop
            tp_hit = float(row["low"]) <= target

        # Stop wins all same-M1 ambiguity. TP cannot be credited on fill M1.
        if sl_hit:
            pnl = stop - entry if direction == "LONG" else entry - stop
            return {
                "exit_reason": "SL_ENTRY_BAR_CONSERVATIVE" if idx == fill_index else "SL",
                "exit_at": ensure_utc(timestamps[idx].to_pydatetime()).isoformat(),
                "exit_price": stop,
                "gross_points": pnl,
            }
        if idx > fill_index and tp_hit:
            pnl = target - entry if direction == "LONG" else entry - target
            return {
                "exit_reason": "TP",
                "exit_at": ensure_utc(timestamps[idx].to_pydatetime()).isoformat(),
                "exit_price": target,
                "gross_points": pnl,
            }

    if end <= fill_index:
        return {"exit_reason": "NO_HORIZON", "gross_points": None}
    last = price.iloc[end - 1]
    exit_price = float(last["close"])
    pnl = exit_price - entry if direction == "LONG" else entry - exit_price
    return {
        "exit_reason": "TIME_EXIT_16H",
        "exit_at": ensure_utc(timestamps[end - 1].to_pydatetime()).isoformat(),
        "exit_price": exit_price,
        "gross_points": pnl,
    }


def generate_year(price: pd.DataFrame, *, year: int) -> dict[str, Any]:
    zones = build_zones(price)
    px: PriceIndex = _price_index(price)
    superseded = causal_superseded_at(zones)
    invalidated = {
        zone.zone_id: _first_invalidation_at(
            price,
            zone=zone,
            index=px,
            valid_until=superseded.get(zone.zone_id),
        )
        for zone in zones
    }

    h1_zones = [zone for zone in zones if zone.timeframe == "H1"]
    m15_zones = [zone for zone in zones if zone.timeframe == "M15"]
    h4 = _h4_context(price)

    m5_frame = _resample_ohlc(price, "5min")
    m5_zones = list(_detect_m5_zones(m5_frame))
    m5_superseded = _m5_superseded_at(m5_zones)
    m5_invalidated = _first_invalidation_map(price, m5_zones, m5_superseded)

    trades: list[dict[str, Any]] = []
    diagnostics = {
        "h1_first_touches": 0,
        "h4_aligned": 0,
        "nested_m15": 0,
        "nested_m5": 0,
        "candidate_slots": 0,
    }

    for parent in h1_zones:
        episode = evaluate_first_touch(
            price,
            zone=parent,
            index=px,
            valid_until=superseded.get(parent.zone_id),
        )
        if episode is None or ensure_utc(episode.touch_at).year != year:
            continue
        diagnostics["h1_first_touches"] += 1
        touch_at = ensure_utc(episode.touch_at)

        # Only completed H4 information before the first H1 touch may authorize
        # the continuation direction.
        if _h4_direction_at(h4, touch_at) != parent.direction:
            continue
        diagnostics["h4_aligned"] += 1

        nested_m15 = [
            zone
            for zone in m15_zones
            if zone.direction == parent.direction
            and ensure_utc(zone.available_at) < touch_at
            and _active_at(zone, invalidated, superseded, touch_at)
            and _overlap_fraction(zone, parent) >= 0.50
        ]
        nested_m15.sort(key=lambda zone: _nested_rank(zone, parent))
        if not nested_m15:
            continue
        m15 = nested_m15[0]
        diagnostics["nested_m15"] += 1

        nested_m5 = [
            zone
            for zone in m5_zones
            if zone.direction == parent.direction
            and ensure_utc(zone.available_at) < touch_at
            and _m5_active_at(
                zone,
                touch_at,
                superseded=m5_superseded,
                invalidated=m5_invalidated,
            )
            and _overlap_fraction(zone, m15) >= 0.50
        ]
        nested_m5.sort(key=lambda zone: _nested_rank(zone, m15))
        if not nested_m5:
            continue
        m5 = nested_m5[0]
        diagnostics["nested_m5"] += 1

        near_edge = float(m5.high) if parent.direction == "LONG" else float(m5.low)
        midpoint = (float(m5.low) + float(m5.high)) / 2.0
        valid_until = _valid_until_m5(
            m5,
            superseded=m5_superseded,
            invalidated=m5_invalidated,
            touch_at=touch_at,
        )

        for slot, entry in (("NEAR_EDGE", near_edge), ("MIDPOINT", midpoint)):
            fill_index, fill_at = _find_fill(
                price,
                level=entry,
                start_at=touch_at,
                valid_until=valid_until,
            )
            if fill_index is None or fill_at is None or fill_at.year != year:
                continue

            stop = (
                float(parent.distal) - STOP_BUFFER_ATR * float(parent.atr_points)
                if parent.direction == "LONG"
                else float(parent.distal) + STOP_BUFFER_ATR * float(parent.atr_points)
            )
            risk = entry - stop if parent.direction == "LONG" else stop - entry
            if not isfinite(risk) or risk <= 0:
                continue

            diagnostics["candidate_slots"] += 1
            for target_policy in TARGET_POLICIES:
                terminal_zone_id = None
                if target_policy == "R2":
                    target = (
                        entry + FIXED_R_TARGET * risk
                        if parent.direction == "LONG"
                        else entry - FIXED_R_TARGET * risk
                    )
                    rr = FIXED_R_TARGET
                else:
                    target, terminal_zone_id = _terminal_h1_target(
                        h1_zones,
                        direction=parent.direction,
                        entry=entry,
                        at=touch_at,
                        invalidated=invalidated,
                        superseded=superseded,
                    )
                    if target is None:
                        continue
                    reward = (
                        target - entry
                        if parent.direction == "LONG"
                        else entry - target
                    )
                    rr = reward / risk if risk > 0 else 0.0
                    if reward <= 0 or rr + 1e-12 < MIN_TERMINAL_RR:
                        continue

                if target <= 0:
                    continue
                outcome = _resolve(
                    price,
                    fill_index=fill_index,
                    fill_at=fill_at,
                    entry=entry,
                    stop=stop,
                    target=float(target),
                    direction=parent.direction,
                )
                if outcome.get("gross_points") is None:
                    continue
                trades.append(
                    {
                        "year": year,
                        "variant_id": f"V234_H1SD_M5_{target_policy}",
                        "family": "H4_H1_SD_M15_M5_CONTINUATION",
                        "direction": parent.direction,
                        "slot": slot,
                        "h1_zone_id": parent.zone_id,
                        "m15_zone_id": m15.zone_id,
                        "m5_zone_id": m5.zone_id,
                        "terminal_h1_zone_id": terminal_zone_id,
                        "h1_touch_at": touch_at.isoformat(),
                        "fill_at": ensure_utc(fill_at).isoformat(),
                        "entry": entry,
                        "sl": stop,
                        "tp": float(target),
                        "risk_points": risk,
                        "rr": rr,
                        "target_policy": target_policy,
                        "margin_usd_1_to_100": entry / 100.0,
                        "exit_reason": outcome["exit_reason"],
                        "exit_at": outcome["exit_at"],
                        "exit_price": outcome["exit_price"],
                        "gross_points": float(outcome["gross_points"]),
                        "gross_pnl_usd": float(outcome["gross_points"]),
                        "fixed_lot_reference": 0.01,
                    }
                )

    trades.sort(
        key=lambda row: (
            row["fill_at"],
            row["variant_id"],
            row["h1_zone_id"],
            row["slot"],
        )
    )
    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "year": year,
        "architecture": {
            "H4": "COMPLETED_H4_EMA20_50_200_TREND_AUTHORITY",
            "H1": "FRESH_FIRST_TOUCH_SUPPLY_DEMAND_PARENT_ALIGNED_TO_H4",
            "M15": "PREEXISTING_ACTIVE_SAME_DIRECTION_CHILD_OVERLAP_GTE_50PCT",
            "M5": "PREEXISTING_ACTIVE_SAME_DIRECTION_CHILD_OVERLAP_GTE_50PCT",
            "entries": ["M5_NEAR_EDGE", "M5_MIDPOINT"],
            "stop": "H1_DISTAL_PLUS_0_15_ATR",
            "targets": ["FIXED_2R", "NEAREST_ACTIVE_OPPOSING_H1_ZONE_RR_GTE_1"],
            "entry_horizon_hours": ENTRY_HORIZON_HOURS,
            "max_hold_hours": MAX_HOLD_HOURS,
        },
        "diagnostics": diagnostics,
        "trades": trades,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    year = _year()
    price_path = os.getenv(
        "XAU_V234_PRICE_CSV",
        f"/tmp/histdata/xau-v234-{year}.csv",
    )
    output = Path(
        os.getenv(
            "XAU_V234_OUTPUT",
            f"artifacts/xau-h4-h1-sd-m15-m5-continuation-v234-{year}.json",
        )
    )
    result = generate_year(_load_price_frame(price_path), year=year)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_V234_YEAR "
        f"year={year} trades={len(result['trades'])} "
        f"h1={result['diagnostics']['h1_first_touches']} "
        f"m5={result['diagnostics']['nested_m5']} authority=SHADOW_ONLY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

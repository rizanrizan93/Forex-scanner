from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import timedelta
from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .models import ensure_utc
from .research_xau_zone_reversal_depth_v225 import (
    DepthEpisode,
    REACTION_HORIZON_MINUTES,
)

REACTION_LADDER = (0.25, 0.50, 0.75, 1.00)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.quantile(np.asarray(values, dtype=float), q))


def _episode_metrics(price_m1: pd.DataFrame, row: DepthEpisode) -> dict[str, Any]:
    timestamps = tuple(pd.Timestamp(value) for value in price_m1["timestamp"])
    highs = price_m1["high"].to_numpy(dtype=float, copy=False)
    lows = price_m1["low"].to_numpy(dtype=float, copy=False)
    closes = price_m1["close"].to_numpy(dtype=float, copy=False)

    touch_at = ensure_utc(row.touch_at)
    start = bisect_left(timestamps, pd.Timestamp(touch_at))
    horizon_end = touch_at + timedelta(minutes=REACTION_HORIZON_MINUTES[row.timeframe])
    end = bisect_right(timestamps, pd.Timestamp(horizon_end))
    if start >= len(timestamps) or end <= start:
        return {
            "zone_id": row.zone_id,
            "timeframe": row.timeframe,
            "direction": row.direction,
            "touch_at": touch_at.isoformat(),
            "available_at": ensure_utc(row.available_at).isoformat(),
            "candidate_to_first_touch_minutes": max(
                0.0,
                (touch_at - ensure_utc(row.available_at)).total_seconds() / 60.0,
            ),
            "complete": False,
        }

    window_high = highs[start:end]
    window_low = lows[start:end]
    window_close = closes[start:end]
    if row.direction == "LONG":
        break_mask = window_close < float(row.distal)
    else:
        break_mask = window_close > float(row.distal)
    break_positions = np.flatnonzero(break_mask)
    break_rel = int(break_positions[0]) if len(break_positions) else None

    target_hits: dict[str, bool] = {}
    target_minutes: dict[str, float | None] = {}
    for multiple in REACTION_LADDER:
        if row.direction == "LONG":
            target = float(row.proximal) + multiple * float(row.atr_points)
            target_mask = window_high >= target
        else:
            target = float(row.proximal) - multiple * float(row.atr_points)
            target_mask = window_low <= target
        positions = np.flatnonzero(target_mask)
        first_target = int(positions[0]) if len(positions) else None
        hit = first_target is not None and (break_rel is None or first_target < break_rel)
        key = f"{multiple:.2f}"
        target_hits[key] = bool(hit)
        target_minutes[key] = (
            None
            if not hit or first_target is None
            else max(
                0.0,
                (
                    ensure_utc(timestamps[start + first_target].to_pydatetime())
                    - touch_at
                ).total_seconds()
                / 60.0,
            )
        )

    favorable_end = end if break_rel is None else start + break_rel
    if favorable_end <= start:
        mfe_atr = 0.0
    elif row.direction == "LONG":
        mfe_atr = max(
            0.0,
            (float(np.max(highs[start:favorable_end])) - float(row.proximal))
            / max(float(row.atr_points), 1e-12),
        )
    else:
        mfe_atr = max(
            0.0,
            (float(row.proximal) - float(np.min(lows[start:favorable_end])))
            / max(float(row.atr_points), 1e-12),
        )

    adverse_end = end if break_rel is None else min(end, start + break_rel + 1)
    if row.direction == "LONG":
        mae_atr = max(
            0.0,
            (float(row.proximal) - float(np.min(lows[start:adverse_end])))
            / max(float(row.atr_points), 1e-12),
        )
    else:
        mae_atr = max(
            0.0,
            (float(np.max(highs[start:adverse_end])) - float(row.proximal))
            / max(float(row.atr_points), 1e-12),
        )

    return {
        "zone_id": row.zone_id,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "touch_at": touch_at.isoformat(),
        "available_at": ensure_utc(row.available_at).isoformat(),
        "candidate_to_first_touch_minutes": max(
            0.0,
            (touch_at - ensure_utc(row.available_at)).total_seconds() / 60.0,
        ),
        "reaction_hits": target_hits,
        "time_to_reaction_minutes": target_minutes,
        "mfe_atr": float(mfe_atr),
        "mae_atr": float(mae_atr),
        "break_before_horizon": break_rel is not None,
        "complete": True,
    }


def build_excursion_metrics(
    price_m1: pd.DataFrame,
    episodes: Sequence[DepthEpisode],
) -> list[dict[str, Any]]:
    if price_m1.empty:
        return []
    frame = price_m1.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp", "high", "low", "close"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return [_episode_metrics(frame, row) for row in episodes]


def summarize_excursions(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if bool(row.get("complete"))]
    if not complete:
        return {
            "episodes": 0,
            "reaction_rates": {f"{m:.2f}": None for m in REACTION_LADDER},
            "mfe_atr_median": None,
            "mae_atr_median": None,
            "candidate_to_first_touch_minutes_median": None,
            "time_to_reaction_minutes_median": {f"{m:.2f}": None for m in REACTION_LADDER},
            "break_before_horizon_rate": None,
        }

    reaction_rates: dict[str, float] = {}
    time_to_reaction: dict[str, float | None] = {}
    for multiple in REACTION_LADDER:
        key = f"{multiple:.2f}"
        hits = [bool(dict(row["reaction_hits"]).get(key)) for row in complete]
        reaction_rates[key] = sum(hits) / len(hits)
        times = [
            float(dict(row["time_to_reaction_minutes"])[key])
            for row in complete
            if dict(row["time_to_reaction_minutes"]).get(key) is not None
        ]
        time_to_reaction[key] = None if not times else float(median(times))

    mfe = [float(row["mfe_atr"]) for row in complete]
    mae = [float(row["mae_atr"]) for row in complete]
    first_touch = [float(row["candidate_to_first_touch_minutes"]) for row in complete]

    return {
        "episodes": len(complete),
        "reaction_rates": reaction_rates,
        "mfe_atr_p25": _quantile(mfe, 0.25),
        "mfe_atr_median": _quantile(mfe, 0.50),
        "mfe_atr_p75": _quantile(mfe, 0.75),
        "mae_atr_p25": _quantile(mae, 0.25),
        "mae_atr_median": _quantile(mae, 0.50),
        "mae_atr_p75": _quantile(mae, 0.75),
        "candidate_to_first_touch_minutes_median": float(median(first_touch)),
        "time_to_reaction_minutes_median": time_to_reaction,
        "break_before_horizon_rate": sum(
            bool(row["break_before_horizon"]) for row in complete
        ) / len(complete),
    }


def grouped_excursion_report(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {"ALL": summarize_excursions(rows)}
    for timeframe in ("H4", "H1", "M15"):
        tf_rows = [row for row in rows if row.get("timeframe") == timeframe]
        output[timeframe] = {
            "ALL": summarize_excursions(tf_rows),
            "LONG": summarize_excursions(
                [row for row in tf_rows if row.get("direction") == "LONG"]
            ),
            "SHORT": summarize_excursions(
                [row for row in tf_rows if row.get("direction") == "SHORT"]
            ),
        }
    return output

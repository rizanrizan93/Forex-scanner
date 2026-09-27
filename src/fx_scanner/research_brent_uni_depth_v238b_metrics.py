from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class PriceArrays:
    timestamps: tuple[pd.Timestamp, ...]
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray


def _price_arrays(price_m1: pd.DataFrame) -> PriceArrays:
    frame = price_m1.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp", "high", "low", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return PriceArrays(
        timestamps=tuple(pd.Timestamp(value) for value in frame["timestamp"]),
        highs=frame["high"].to_numpy(dtype=float, copy=False),
        lows=frame["low"].to_numpy(dtype=float, copy=False),
        closes=frame["close"].to_numpy(dtype=float, copy=False),
    )


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.quantile(np.asarray(values, dtype=float), q))


def _episode_metrics(px: PriceArrays, row: DepthEpisode) -> dict[str, Any]:
    touch_at = ensure_utc(row.touch_at)
    start = bisect_left(px.timestamps, pd.Timestamp(touch_at))
    horizon_end = touch_at + timedelta(minutes=REACTION_HORIZON_MINUTES[row.timeframe])
    end = bisect_right(px.timestamps, pd.Timestamp(horizon_end))
    base = {
        "zone_id": row.zone_id,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "touch_at": touch_at.isoformat(),
        "available_at": ensure_utc(row.available_at).isoformat(),
        "candidate_to_first_touch_minutes": max(
            0.0,
            (touch_at - ensure_utc(row.available_at)).total_seconds() / 60.0,
        ),
    }
    if start >= len(px.timestamps) or end <= start:
        return {**base, "complete": False}

    window_high = px.highs[start:end]
    window_low = px.lows[start:end]
    window_close = px.closes[start:end]
    break_mask = (
        window_close < float(row.distal)
        if row.direction == "LONG"
        else window_close > float(row.distal)
    )
    break_positions = np.flatnonzero(break_mask)
    break_rel = int(break_positions[0]) if len(break_positions) else None

    # Do not turn a truncated year-end horizon into a false negative. A break
    # resolves the episode immediately; otherwise require the full configured
    # horizon before scoring any reaction rung.
    horizon_complete = (
        bool(px.timestamps)
        and px.timestamps[-1] >= pd.Timestamp(horizon_end)
    )
    if break_rel is None and not horizon_complete:
        return {**base, "complete": False, "censored": True}

    # Favorable reaction starts strictly after the first-touch M1 bar.
    # The touch bar can contain both the adverse entry into the zone and a
    # favorable excursion, but their ordering is unknowable.
    future_high = window_high[1:]
    future_low = window_low[1:]

    target_hits: dict[str, bool] = {}
    target_minutes: dict[str, float | None] = {}
    for multiple in REACTION_LADDER:
        if row.direction == "LONG":
            target = float(row.proximal) + multiple * float(row.atr_points)
            target_mask = future_high >= target
        else:
            target = float(row.proximal) - multiple * float(row.atr_points)
            target_mask = future_low <= target
        positions = np.flatnonzero(target_mask)
        first_target = (int(positions[0]) + 1) if len(positions) else None
        # STOP_FIRST for same-M1 ambiguity: a break on the same bar wins.
        hit = first_target is not None and (break_rel is None or first_target < break_rel)
        key = f"{multiple:.2f}"
        target_hits[key] = bool(hit)
        target_minutes[key] = (
            None
            if not hit or first_target is None
            else max(
                0.0,
                (
                    ensure_utc(px.timestamps[start + first_target].to_pydatetime())
                    - touch_at
                ).total_seconds()
                / 60.0,
            )
        )

    favorable_start = start + 1
    favorable_end = end if break_rel is None else start + break_rel
    if favorable_end <= favorable_start:
        mfe_atr = 0.0
    elif row.direction == "LONG":
        mfe_atr = max(
            0.0,
            (float(np.max(px.highs[favorable_start:favorable_end])) - float(row.proximal))
            / max(float(row.atr_points), 1e-12),
        )
    else:
        mfe_atr = max(
            0.0,
            (float(row.proximal) - float(np.min(px.lows[favorable_start:favorable_end])))
            / max(float(row.atr_points), 1e-12),
        )

    adverse_end = end if break_rel is None else min(end, start + break_rel + 1)
    if row.direction == "LONG":
        mae_atr = max(
            0.0,
            (float(row.proximal) - float(np.min(px.lows[start:adverse_end])))
            / max(float(row.atr_points), 1e-12),
        )
    else:
        mae_atr = max(
            0.0,
            (float(np.max(px.highs[start:adverse_end])) - float(row.proximal))
            / max(float(row.atr_points), 1e-12),
        )

    return {
        **base,
        "reaction_hits": target_hits,
        "time_to_reaction_minutes": target_minutes,
        "mfe_atr": float(mfe_atr),
        "mae_atr": float(mae_atr),
        "break_before_horizon": break_rel is not None,
        "censored": False,
        "complete": True,
    }


def build_excursion_metrics(
    price_m1: pd.DataFrame,
    episodes: Sequence[DepthEpisode],
) -> list[dict[str, Any]]:
    if price_m1.empty:
        return []
    px = _price_arrays(price_m1)
    return [_episode_metrics(px, row) for row in episodes]


def summarize_excursions(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if bool(row.get("complete"))]
    if not complete:
        return {
            "episodes": 0,
            "reaction_rates": {f"{m:.2f}": None for m in REACTION_LADDER},
            "mfe_atr_median": None,
            "mae_atr_median": None,
            "candidate_to_first_touch_minutes_median": None,
            "time_to_reaction_minutes_median": {
                f"{m:.2f}": None for m in REACTION_LADDER
            },
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
        )
        / len(complete),
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

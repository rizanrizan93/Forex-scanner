from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_pressure_depth_v246 import (
    PressureDepthEpisode,
    condition_depth_episodes,
)
from .research_xau_zone_reversal_depth_v225 import (
    DepthEpisode,
    REACTION_HORIZON_MINUTES,
)

RESEARCH_VERSION = "XAU_PRESSURE_DEPTH_STRATEGY_V248_1"
ARTIFACT_CONTRACT = "XAU_PRESSURE_DEPTH_STRATEGY_V248_1_EVIDENCE_1"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

STOP_BUFFER_ATR = 0.05

ENTRY_MAPS = {
    "FIXED20": {
        "COUNTER_STRONG": 0.20,
        "COUNTER_MODERATE": 0.20,
        "BALANCED": 0.20,
        "OPPOSING_MODERATE": 0.20,
        "OPPOSING_STRONG": 0.20,
    },
    "ADAPTIVE": {
        "COUNTER_STRONG": 0.10,
        "COUNTER_MODERATE": 0.15,
        "BALANCED": 0.20,
        "OPPOSING_MODERATE": 0.35,
        "OPPOSING_STRONG": 0.50,
    },
    "ADAPTIVE_DEEP": {
        "COUNTER_STRONG": 0.10,
        "COUNTER_MODERATE": 0.15,
        "BALANCED": 0.22,
        "OPPOSING_MODERATE": 0.40,
        "OPPOSING_STRONG": 0.60,
    },
}
TARGET_R = (1.0, 1.5)


@dataclass(frozen=True, slots=True)
class TradeResult:
    variant: str
    timeframe: str
    direction: str
    touch_at: str
    pressure_bucket: str
    opposing_pressure_score: float
    entry_depth: float
    filled: bool
    outcome: str
    r_multiple: float
    bars_to_fill: int | None


def _price_at_depth(episode: DepthEpisode, depth: float) -> float:
    d = min(max(float(depth), 0.0), 1.0)
    width = float(episode.zone_high) - float(episode.zone_low)
    if episode.direction == "LONG":
        return float(episode.zone_high) - d * width
    return float(episode.zone_low) + d * width


def _stop_price(episode: DepthEpisode) -> float:
    buffer = STOP_BUFFER_ATR * float(episode.atr_points)
    if episode.direction == "LONG":
        return float(episode.distal) - buffer
    return float(episode.distal) + buffer


def _target_price(*, direction: str, entry: float, stop: float, rr: float) -> float:
    risk = abs(float(entry) - float(stop))
    return float(entry) + risk * float(rr) if direction == "LONG" else float(entry) - risk * float(rr)


def _frame_index(price_m1: pd.DataFrame) -> tuple[tuple[pd.Timestamp, ...], np.ndarray, np.ndarray, np.ndarray]:
    return (
        tuple(pd.Timestamp(x) for x in price_m1["timestamp"]),
        price_m1["high"].to_numpy(dtype=float, copy=False),
        price_m1["low"].to_numpy(dtype=float, copy=False),
        price_m1["close"].to_numpy(dtype=float, copy=False),
    )


def evaluate_trade(
    price_m1: pd.DataFrame,
    *,
    episode: DepthEpisode,
    pressure: PressureDepthEpisode,
    entry_depth: float,
    rr: float,
    index: tuple[tuple[pd.Timestamp, ...], np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> TradeResult:
    timestamps, highs, lows, closes = _frame_index(price_m1) if index is None else index
    touch = pd.Timestamp(episode.touch_at)
    horizon = touch + pd.Timedelta(minutes=int(REACTION_HORIZON_MINUTES[episode.timeframe]))
    start = bisect_left(timestamps, touch)
    end = bisect_right(timestamps, horizon)
    entry = _price_at_depth(episode, entry_depth)
    stop = _stop_price(episode)
    risk = abs(entry - stop)
    target = _target_price(direction=episode.direction, entry=entry, stop=stop, rr=rr)
    variant = f"{'FIXED' if abs(entry_depth-0.20)<1e-12 else 'ADAPT'}_R{rr:.1f}"

    if risk <= 1e-12 or start >= end:
        return TradeResult(
            variant=variant,
            timeframe=episode.timeframe,
            direction=episode.direction,
            touch_at=episode.touch_at.isoformat(),
            pressure_bucket=pressure.opposing_pressure_bucket,
            opposing_pressure_score=float(pressure.opposing_pressure_score),
            entry_depth=float(entry_depth),
            filled=False,
            outcome="NO_DATA",
            r_multiple=0.0,
            bars_to_fill=None,
        )

    fill_idx: int | None = None
    for i in range(start, end):
        if lows[i] <= entry <= highs[i]:
            fill_idx = i
            break
    if fill_idx is None:
        return TradeResult(
            variant=variant,
            timeframe=episode.timeframe,
            direction=episode.direction,
            touch_at=episode.touch_at.isoformat(),
            pressure_bucket=pressure.opposing_pressure_bucket,
            opposing_pressure_score=float(pressure.opposing_pressure_score),
            entry_depth=float(entry_depth),
            filled=False,
            outcome="NO_FILL",
            r_multiple=0.0,
            bars_to_fill=None,
        )

    for i in range(fill_idx, end):
        if episode.direction == "LONG":
            hit_stop = lows[i] <= stop
            hit_target = highs[i] >= target
        else:
            hit_stop = highs[i] >= stop
            hit_target = lows[i] <= target

        # Conservative intrabar rule: if both are printed on the same M1 bar,
        # the stop wins because tick ordering is unavailable in HistData M1.
        if hit_stop:
            return TradeResult(
                variant=variant,
                timeframe=episode.timeframe,
                direction=episode.direction,
                touch_at=episode.touch_at.isoformat(),
                pressure_bucket=pressure.opposing_pressure_bucket,
                opposing_pressure_score=float(pressure.opposing_pressure_score),
                entry_depth=float(entry_depth),
                filled=True,
                outcome="STOP",
                r_multiple=-1.0,
                bars_to_fill=fill_idx - start,
            )
        if hit_target:
            return TradeResult(
                variant=variant,
                timeframe=episode.timeframe,
                direction=episode.direction,
                touch_at=episode.touch_at.isoformat(),
                pressure_bucket=pressure.opposing_pressure_bucket,
                opposing_pressure_score=float(pressure.opposing_pressure_score),
                entry_depth=float(entry_depth),
                filled=True,
                outcome="TARGET",
                r_multiple=float(rr),
                bars_to_fill=fill_idx - start,
            )

    exit_price = float(closes[end - 1])
    pnl = exit_price - entry if episode.direction == "LONG" else entry - exit_price
    timeout_r = max(-1.0, min(float(rr), pnl / risk))
    return TradeResult(
        variant=variant,
        timeframe=episode.timeframe,
        direction=episode.direction,
        touch_at=episode.touch_at.isoformat(),
        pressure_bucket=pressure.opposing_pressure_bucket,
        opposing_pressure_score=float(pressure.opposing_pressure_score),
        entry_depth=float(entry_depth),
        filled=True,
        outcome="TIMEOUT",
        r_multiple=float(timeout_r),
        bars_to_fill=fill_idx - start,
    )


def build_variant_results(
    price_m1: pd.DataFrame,
    depth_episodes: Sequence[DepthEpisode],
) -> dict[str, tuple[TradeResult, ...]]:
    pressure_rows = condition_depth_episodes(price_m1, depth_episodes)
    pressure_by_key = {
        (row.zone_id, row.timeframe, row.direction, row.touch_at): row
        for row in pressure_rows
    }
    idx = _frame_index(price_m1)
    output: dict[str, list[TradeResult]] = {}

    for episode in depth_episodes:
        key = (
            episode.zone_id,
            episode.timeframe,
            episode.direction,
            episode.touch_at.isoformat(),
        )
        pressure = pressure_by_key.get(key)
        if pressure is None:
            continue
        for map_name, mapping in ENTRY_MAPS.items():
            depth = float(mapping[pressure.opposing_pressure_bucket])
            for rr in TARGET_R:
                result = evaluate_trade(
                    price_m1,
                    episode=episode,
                    pressure=pressure,
                    entry_depth=depth,
                    rr=rr,
                    index=idx,
                )
                variant = f"{map_name}_R{rr:.1f}"
                result = TradeResult(
                    variant=variant,
                    timeframe=result.timeframe,
                    direction=result.direction,
                    touch_at=result.touch_at,
                    pressure_bucket=result.pressure_bucket,
                    opposing_pressure_score=result.opposing_pressure_score,
                    entry_depth=result.entry_depth,
                    filled=result.filled,
                    outcome=result.outcome,
                    r_multiple=result.r_multiple,
                    bars_to_fill=result.bars_to_fill,
                )
                output.setdefault(variant, []).append(result)
    return {key: tuple(value) for key, value in output.items()}


def _max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def summarize_results(rows: Sequence[TradeResult], *, cost_r: float = 0.0) -> dict[str, Any]:
    episodes = list(rows)
    filled = [row for row in episodes if row.filled]
    adjusted = [float(row.r_multiple) - float(cost_r) for row in filled]
    wins = [r for r in adjusted if r > 0]
    losses = [r for r in adjusted if r < 0]
    gross_win = float(sum(wins))
    gross_loss = float(-sum(losses))
    return {
        "episodes": len(episodes),
        "fills": len(filled),
        "fill_rate": None if not episodes else len(filled) / len(episodes),
        "targets": sum(row.outcome == "TARGET" for row in filled),
        "stops": sum(row.outcome == "STOP" for row in filled),
        "timeouts": sum(row.outcome == "TIMEOUT" for row in filled),
        "win_rate": None if not filled else len(wins) / len(filled),
        "profit_factor": None if gross_loss <= 1e-12 else gross_win / gross_loss,
        "expectancy_r": None if not filled else float(sum(adjusted)) / len(filled),
        "net_r": float(sum(adjusted)),
        "gross_win_r": gross_win,
        "gross_loss_r": gross_loss,
        "max_drawdown_r": _max_drawdown(adjusted),
        "cost_r_per_fill": float(cost_r),
        "r_sequence": adjusted,
    }


def summarize_variants(results: dict[str, tuple[TradeResult, ...]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for variant, rows in results.items():
        output[variant] = {
            "raw": summarize_results(rows, cost_r=0.0),
            "cost_002r": summarize_results(rows, cost_r=0.02),
            "cost_005r": summarize_results(rows, cost_r=0.05),
            "by_timeframe": {
                tf: summarize_results([row for row in rows if row.timeframe == tf], cost_r=0.02)
                for tf in ("H4", "H1", "M15")
            },
            "by_direction": {
                side: summarize_results([row for row in rows if row.direction == side], cost_r=0.02)
                for side in ("LONG", "SHORT")
            },
        }
    return output

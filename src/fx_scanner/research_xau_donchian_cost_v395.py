from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_donchian_regime_v394 import (
    ACTIVE_END_UTC,
    ACTIVE_START_UTC,
    BASE_COST_PRICE,
    EMA_LENGTH,
    EMA_SLOPE_LOOKBACK,
    ENTRY_EXPIRY_BARS,
    MAX_HOLD_BARS,
    RETEST_TOLERANCE_ATR,
    STOP_ATR,
    STRESS_COST_PRICE,
    TARGET_R,
    _efficiency_ratio,
    _resolve_exit_bar,
    prepare_m15,
    summarize,
    training_score,
)

RESEARCH_VERSION = "V395"
ARTIFACT_CONTRACT = "XAU_DONCHIAN_COST_AWARE_RAW_WALKFORWARD_V395_1"
SYMBOL = "XAUUSD"


@dataclass(frozen=True)
class CostAwareConfig:
    channel_length: int
    efficiency_lookback: int
    min_efficiency: float
    min_vol_ratio: float
    max_stress_cost_r: float

    @property
    def config_id(self) -> str:
        return (
            f"D{self.channel_length}_ER{self.efficiency_lookback}_"
            f"E{self.min_efficiency:.2f}_V{self.min_vol_ratio:.2f}_"
            f"C{self.max_stress_cost_r:.2f}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[CostAwareConfig]:
    return [
        CostAwareConfig(*values)
        for values in itertools.product(
            (20, 40),
            (16, 32),
            (0.20, 0.30),
            (0.80, 1.00),
            (0.25, 0.30),
        )
    ]


def simulate_config(
    m15: pd.DataFrame,
    config: CostAwareConfig,
    *,
    target_year: int,
    entry_expiry_bars: int = ENTRY_EXPIRY_BARS,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> list[dict[str, Any]]:
    data = m15.copy()
    upper = data["high"].shift(1).rolling(config.channel_length, min_periods=config.channel_length).max()
    lower = data["low"].shift(1).rolling(config.channel_length, min_periods=config.channel_length).min()
    efficiency = _efficiency_ratio(data["close"], config.efficiency_lookback).shift(1)
    active = (data["utc_hour"] >= ACTIVE_START_UTC) & (data["utc_hour"] < ACTIVE_END_UTC)
    regime = (efficiency >= config.min_efficiency) & (data["vol_ratio"] >= config.min_vol_ratio)

    long_signal = (
        active
        & regime
        & (data["close"] > upper)
        & (data["close"] > data["ema200"])
        & (data["ema_slope8"] > 0)
        & (data["body_fraction"] >= 0.50)
        & (data["close_position"] >= 0.65)
    )
    short_signal = (
        active
        & regime
        & (data["close"] < lower)
        & (data["close"] < data["ema200"])
        & (data["ema_slope8"] < 0)
        & (data["body_fraction"] >= 0.50)
        & (data["close_position"] <= 0.35)
    )

    signal_indexes = np.flatnonzero((long_signal | short_signal).to_numpy())
    timestamps = data["timestamp"].to_numpy()
    highs = data["high"].to_numpy(dtype=float)
    lows = data["low"].to_numpy(dtype=float)
    closes = data["close"].to_numpy(dtype=float)
    atr = data["atr14"].to_numpy(dtype=float)
    upper_a = upper.to_numpy(dtype=float)
    lower_a = lower.to_numpy(dtype=float)
    long_a = long_signal.to_numpy(dtype=bool)
    years = data["timestamp"].dt.year.to_numpy(dtype=int)
    efficiency_a = efficiency.to_numpy(dtype=float)
    vol_ratio_a = data["vol_ratio"].to_numpy(dtype=float)

    trades: list[dict[str, Any]] = []
    next_allowed = 0
    for index in signal_indexes:
        if index < next_allowed or int(years[index]) != target_year:
            continue
        if not np.isfinite(atr[index]) or atr[index] <= 0.0:
            continue

        risk_price = STOP_ATR * atr[index]
        stress_cost_r = STRESS_COST_PRICE / risk_price
        if stress_cost_r > config.max_stress_cost_r:
            continue

        side = 1 if long_a[index] else -1
        level = upper_a[index] if side > 0 else lower_a[index]
        if not np.isfinite(level):
            continue

        tolerance = RETEST_TOLERANCE_ATR * atr[index]
        fill_index: int | None = None
        for candidate in range(index + 1, min(index + entry_expiry_bars + 1, len(data))):
            if side > 0:
                touched = lows[candidate] <= level + tolerance and highs[candidate] >= level
            else:
                touched = highs[candidate] >= level - tolerance and lows[candidate] <= level
            if touched:
                fill_index = candidate
                break
        if fill_index is None:
            continue

        entry = float(level)
        stop = entry - side * risk_price
        target = entry + side * TARGET_R * risk_price

        exit_index: int | None = None
        gross_r: float | None = None
        state = "TIME_EXIT"
        for candidate in range(fill_index, min(fill_index + max_hold_bars, len(data))):
            outcome = _resolve_exit_bar(
                side=side,
                low=float(lows[candidate]),
                high=float(highs[candidate]),
                stop=float(stop),
                target=float(target),
            )
            if outcome == "LOSS":
                exit_index = candidate
                gross_r = -1.0
                state = "LOSS"
                break
            if outcome == "WIN":
                exit_index = candidate
                gross_r = TARGET_R
                state = "WIN"
                break
        if exit_index is None:
            exit_index = min(fill_index + max_hold_bars - 1, len(data) - 1)
            gross_r = ((closes[exit_index] - entry) * side) / risk_price

        trades.append(
            {
                "config_id": config.config_id,
                "year": int(target_year),
                "signal_at": pd.Timestamp(timestamps[index]).isoformat(),
                "entry_at": pd.Timestamp(timestamps[fill_index]).isoformat(),
                "exit_at": pd.Timestamp(timestamps[exit_index]).isoformat(),
                "direction": "LONG" if side > 0 else "SHORT",
                "efficiency_ratio": float(efficiency_a[index]),
                "vol_ratio": float(vol_ratio_a[index]),
                "stress_cost_r_at_signal": float(stress_cost_r),
                "entry": entry,
                "stop": float(stop),
                "target": float(target),
                "risk_price": float(risk_price),
                "gross_r": float(gross_r),
                "state": state,
            }
        )
        next_allowed = exit_index + 1
    return trades

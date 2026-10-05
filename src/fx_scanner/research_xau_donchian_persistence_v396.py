from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .research_xau_donchian_cost_v395 import (
    CostAwareConfig,
    config_grid,
)
from .research_xau_donchian_regime_v394 import (
    ACTIVE_END_UTC,
    ACTIVE_START_UTC,
    BASE_COST_PRICE,
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

RESEARCH_VERSION = "V396"
ARTIFACT_CONTRACT = "XAU_DONCHIAN_PERSISTENT_BREAKOUT_RAW_WALKFORWARD_V396_1"
SYMBOL = "XAUUSD"
MIN_BREAKOUT_DISTANCE_ATR = 0.10


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

    # Prior-bar-only signed net movement. This prevents the breakout candle itself
    # from manufacturing the momentum-alignment condition.
    prior_close = data["close"].shift(1)
    prior_anchor = data["close"].shift(config.efficiency_lookback + 1)
    signed_net = prior_close - prior_anchor

    active = (data["utc_hour"] >= ACTIVE_START_UTC) & (data["utc_hour"] < ACTIVE_END_UTC)
    regime = (efficiency >= config.min_efficiency) & (data["vol_ratio"] >= config.min_vol_ratio)
    breakout_distance = MIN_BREAKOUT_DISTANCE_ATR * data["atr14"]

    long_signal = (
        active
        & regime
        & (signed_net > 0)
        & (data["close"] >= upper + breakout_distance)
        & (data["close"] > data["ema200"])
        & (data["ema_slope8"] > 0)
        & (data["body_fraction"] >= 0.50)
        & (data["close_position"] >= 0.65)
    )
    short_signal = (
        active
        & regime
        & (signed_net < 0)
        & (data["close"] <= lower - breakout_distance)
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
    signed_net_a = signed_net.to_numpy(dtype=float)

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
                "signed_prior_net": float(signed_net_a[index]),
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

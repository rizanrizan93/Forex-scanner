from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_slr_v390 import _resample_ohlc, summarize_trades

RESEARCH_VERSION = "V394"
ARTIFACT_CONTRACT = "XAU_DONCHIAN_REGIME_RAW_WALKFORWARD_V394_1"
SYMBOL = "XAUUSD"
BASE_COST_PRICE = 0.40
STRESS_COST_PRICE = 0.80
ENTRY_EXPIRY_BARS = 6
MAX_HOLD_BARS = 48
ACTIVE_START_UTC = 6
ACTIVE_END_UTC = 20
EMA_LENGTH = 200
EMA_SLOPE_LOOKBACK = 8
RETEST_TOLERANCE_ATR = 0.25
STOP_ATR = 1.0
TARGET_R = 1.5
VOL_MEDIAN_BARS = 96 * 20


@dataclass(frozen=True)
class RegimeConfig:
    channel_length: int
    efficiency_lookback: int
    min_efficiency: float
    min_vol_ratio: float

    @property
    def config_id(self) -> str:
        return (
            f"D{self.channel_length}_ER{self.efficiency_lookback}_"
            f"E{self.min_efficiency:.2f}_V{self.min_vol_ratio:.2f}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[RegimeConfig]:
    return [
        RegimeConfig(*values)
        for values in itertools.product(
            (20, 40),
            (16, 32),
            (0.20, 0.30),
            (0.80, 1.00),
        )
    ]


def prepare_m15(price: pd.DataFrame) -> pd.DataFrame:
    m15 = _resample_ohlc(price, "15min")
    previous_close = m15["close"].shift(1)
    tr = pd.concat(
        [
            m15["high"] - m15["low"],
            (m15["high"] - previous_close).abs(),
            (m15["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    m15["tr"] = tr
    m15["atr14"] = tr.rolling(14, min_periods=14).mean()
    m15["bar_range"] = m15["high"] - m15["low"]
    denom = m15["bar_range"].replace(0.0, np.nan)
    m15["body_fraction"] = (m15["close"] - m15["open"]).abs() / denom
    m15["close_position"] = (m15["close"] - m15["low"]) / denom
    m15["utc_hour"] = m15["timestamp"].dt.hour
    m15["ema200"] = m15["close"].ewm(span=EMA_LENGTH, adjust=False).mean()
    m15["ema_slope8"] = m15["ema200"] - m15["ema200"].shift(EMA_SLOPE_LOOKBACK)
    trailing_median_atr = m15["atr14"].shift(1).rolling(VOL_MEDIAN_BARS, min_periods=96 * 5).median()
    m15["vol_ratio"] = m15["atr14"] / trailing_median_atr
    return m15.reset_index(drop=True)


def _efficiency_ratio(close: pd.Series, lookback: int) -> pd.Series:
    net = (close - close.shift(lookback)).abs()
    path = close.diff().abs().rolling(lookback, min_periods=lookback).sum()
    return net / path.replace(0.0, np.nan)


def _resolve_exit_bar(*, side: int, low: float, high: float, stop: float, target: float) -> str | None:
    stop_hit = low <= stop if side > 0 else high >= stop
    target_hit = high >= target if side > 0 else low <= target
    if stop_hit:
        return "LOSS"
    if target_hit:
        return "WIN"
    return None


def simulate_config(
    m15: pd.DataFrame,
    config: RegimeConfig,
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
        risk_price = STOP_ATR * atr[index]
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
                "entry": float(entry),
                "stop": float(stop),
                "target": float(target),
                "risk_price": float(risk_price),
                "gross_r": float(gross_r),
                "state": state,
            }
        )
        next_allowed = exit_index + 1
    return trades


def summarize(trades: Sequence[dict[str, Any]], *, cost_price: float) -> dict[str, Any]:
    return summarize_trades(trades, cost_price=cost_price)


def training_score(metrics: dict[str, Any], *, positive_year_ratio: float) -> float:
    n = max(int(metrics.get("completed") or 0), 0)
    if n == 0:
        return -1e9
    pf = max(float(metrics.get("profit_factor_r") or 0.0), 0.01)
    expectancy = float(metrics.get("expectancy_r") or 0.0)
    drawdown = float(metrics.get("max_drawdown_r") or 0.0)
    shrink = np.sqrt(n / (n + 100.0))
    return float(expectancy * shrink + 0.08 * np.log(min(pf, 3.0)) + 0.06 * (positive_year_ratio - 0.5) - 0.003 * drawdown)

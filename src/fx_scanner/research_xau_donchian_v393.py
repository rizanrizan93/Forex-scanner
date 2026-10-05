from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_slr_v390 import _resample_ohlc, summarize_trades

RESEARCH_VERSION = "V393"
ARTIFACT_CONTRACT = "XAU_DONCHIAN_RETEST_RAW_WALKFORWARD_V393_1"
SYMBOL = "XAUUSD"
BASE_COST_PRICE = 0.40
STRESS_COST_PRICE = 0.80
ENTRY_EXPIRY_BARS = 6
MAX_HOLD_BARS = 48
ACTIVE_START_UTC = 6
ACTIVE_END_UTC = 20


@dataclass(frozen=True)
class DonchianConfig:
    channel_length: int
    ema_length: int
    slope_lookback: int
    retest_tolerance_atr: float
    stop_atr: float
    target_r: float

    @property
    def config_id(self) -> str:
        return (
            f"D{self.channel_length}_EMA{self.ema_length}_SLP{self.slope_lookback}_"
            f"RT{self.retest_tolerance_atr:.2f}_S{self.stop_atr:.1f}_T{self.target_r:.1f}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[DonchianConfig]:
    return [
        DonchianConfig(*values)
        for values in itertools.product(
            (20, 40),
            (100, 200),
            (4, 8),
            (0.10, 0.25),
            (1.0, 1.5),
            (1.5, 2.0),
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
    return m15.reset_index(drop=True)


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
    config: DonchianConfig,
    *,
    target_year: int,
    entry_expiry_bars: int = ENTRY_EXPIRY_BARS,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> list[dict[str, Any]]:
    data = m15.copy()
    upper = data["high"].shift(1).rolling(config.channel_length, min_periods=config.channel_length).max()
    lower = data["low"].shift(1).rolling(config.channel_length, min_periods=config.channel_length).min()
    ema = data["close"].ewm(span=config.ema_length, adjust=False).mean()
    ema_slope = ema - ema.shift(config.slope_lookback)
    hours = data["utc_hour"]
    active = (hours >= ACTIVE_START_UTC) & (hours < ACTIVE_END_UTC)
    long_signal = (
        active
        & (data["close"] > upper)
        & (data["close"] > ema)
        & (ema_slope > 0)
        & (data["body_fraction"] >= 0.50)
        & (data["close_position"] >= 0.65)
    )
    short_signal = (
        active
        & (data["close"] < lower)
        & (data["close"] < ema)
        & (ema_slope < 0)
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

    trades: list[dict[str, Any]] = []
    next_allowed = 0
    for index in signal_indexes:
        if index < next_allowed or int(years[index]) != target_year:
            continue
        if not np.isfinite(atr[index]) or atr[index] <= 0:
            continue
        side = 1 if long_a[index] else -1
        level = upper_a[index] if side > 0 else lower_a[index]
        if not np.isfinite(level):
            continue

        fill_index: int | None = None
        tolerance = config.retest_tolerance_atr * atr[index]
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
        stop = entry - side * config.stop_atr * atr[index]
        risk_price = config.stop_atr * atr[index]
        target = entry + side * config.target_r * risk_price

        exit_index: int | None = None
        gross_r: float | None = None
        state = "TIME_EXIT"
        for candidate in range(fill_index, min(fill_index + max_hold_bars, len(data))):
            outcome = _resolve_exit_bar(side=side, low=float(lows[candidate]), high=float(highs[candidate]), stop=float(stop), target=float(target))
            if outcome == "LOSS":
                exit_index = candidate
                gross_r = -1.0
                state = "LOSS"
                break
            if outcome == "WIN":
                exit_index = candidate
                gross_r = float(config.target_r)
                state = "WIN"
                break
        if exit_index is None:
            exit_index = min(fill_index + max_hold_bars - 1, len(data) - 1)
            gross_r = ((closes[exit_index] - entry) * side) / risk_price

        trades.append({
            "config_id": config.config_id,
            "year": int(target_year),
            "signal_at": pd.Timestamp(timestamps[index]).isoformat(),
            "entry_at": pd.Timestamp(timestamps[fill_index]).isoformat(),
            "exit_at": pd.Timestamp(timestamps[exit_index]).isoformat(),
            "direction": "LONG" if side > 0 else "SHORT",
            "channel_level": float(level),
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target),
            "risk_price": float(risk_price),
            "gross_r": float(gross_r),
            "state": state,
        })
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

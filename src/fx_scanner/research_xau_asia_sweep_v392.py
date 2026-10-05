from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_slr_v390 import _resample_ohlc, summarize_trades

RESEARCH_VERSION = "V392"
ARTIFACT_CONTRACT = "XAU_ASIA_SWEEP_RAW_WALKFORWARD_V392_1"
SYMBOL = "XAUUSD"
BASE_COST_PRICE = 0.40
STRESS_COST_PRICE = 0.80
ENTRY_EXPIRY_BARS = 4
MAX_HOLD_BARS = 32
TRADE_WINDOW_END_UTC = 17
MIN_ASIA_BARS = 16
MAX_ASIA_RANGE_ATR = 4.0


@dataclass(frozen=True)
class SweepConfig:
    asia_end_utc: int
    sweep_atr: float
    reclaim_body_fraction: float
    entry_retrace_fraction: float
    stop_buffer_atr: float
    target_r: float

    @property
    def config_id(self) -> str:
        return (
            f"AE{self.asia_end_utc}_S{self.sweep_atr:.2f}_B{self.reclaim_body_fraction:.2f}_"
            f"E{self.entry_retrace_fraction:.2f}_SB{self.stop_buffer_atr:.2f}_T{self.target_r:.1f}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[SweepConfig]:
    return [
        SweepConfig(*values)
        for values in itertools.product(
            (5, 6),
            (0.10, 0.25),
            (0.45, 0.60),
            (0.25, 0.50),
            (0.10, 0.25),
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
    m15["utc_date"] = m15["timestamp"].dt.date
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


def _daily_asia_levels(m15: pd.DataFrame, *, asia_end_utc: int) -> dict[Any, tuple[float, float, float, int]]:
    levels: dict[Any, tuple[float, float, float, int]] = {}
    for day, frame in m15.groupby("utc_date", sort=True):
        asia = frame[(frame["utc_hour"] >= 0) & (frame["utc_hour"] < asia_end_utc)]
        if len(asia) < MIN_ASIA_BARS:
            continue
        last_atr = float(asia["atr14"].iloc[-1])
        if not np.isfinite(last_atr) or last_atr <= 0.0:
            continue
        high = float(asia["high"].max())
        low = float(asia["low"].min())
        if high <= low or (high - low) > MAX_ASIA_RANGE_ATR * last_atr:
            continue
        levels[day] = (high, low, last_atr, len(asia))
    return levels


def simulate_config(
    m15: pd.DataFrame,
    config: SweepConfig,
    *,
    target_year: int,
    entry_expiry_bars: int = ENTRY_EXPIRY_BARS,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> list[dict[str, Any]]:
    levels = _daily_asia_levels(m15, asia_end_utc=config.asia_end_utc)
    timestamps = m15["timestamp"].to_numpy()
    opens = m15["open"].to_numpy(dtype=float)
    highs = m15["high"].to_numpy(dtype=float)
    lows = m15["low"].to_numpy(dtype=float)
    closes = m15["close"].to_numpy(dtype=float)
    atr = m15["atr14"].to_numpy(dtype=float)
    body_fraction = m15["body_fraction"].to_numpy(dtype=float)
    close_position = m15["close_position"].to_numpy(dtype=float)
    hours = m15["utc_hour"].to_numpy(dtype=int)
    dates = m15["utc_date"].to_numpy()
    years = m15["timestamp"].dt.year.to_numpy(dtype=int)

    trades: list[dict[str, Any]] = []
    used_day: set[Any] = set()
    next_allowed = 0

    for index in range(len(m15)):
        day = dates[index]
        if index < next_allowed or day in used_day or int(years[index]) != target_year:
            continue
        if day not in levels:
            continue
        if hours[index] < config.asia_end_utc or hours[index] >= TRADE_WINDOW_END_UTC:
            continue
        if not np.isfinite(atr[index]) or atr[index] <= 0.0:
            continue

        asia_high, asia_low, _, _ = levels[day]
        body_ok = body_fraction[index] >= config.reclaim_body_fraction
        long_signal = bool(
            body_ok
            and lows[index] <= asia_low - config.sweep_atr * atr[index]
            and closes[index] > asia_low
            and closes[index] > opens[index]
            and close_position[index] >= 0.60
        )
        short_signal = bool(
            body_ok
            and highs[index] >= asia_high + config.sweep_atr * atr[index]
            and closes[index] < asia_high
            and closes[index] < opens[index]
            and close_position[index] <= 0.40
        )
        if not (long_signal or short_signal):
            continue

        side = 1 if long_signal else -1
        if side > 0:
            reclaim_span = max(closes[index] - lows[index], 1e-9)
            entry = closes[index] - config.entry_retrace_fraction * reclaim_span
            stop = lows[index] - config.stop_buffer_atr * atr[index]
        else:
            reclaim_span = max(highs[index] - closes[index], 1e-9)
            entry = closes[index] + config.entry_retrace_fraction * reclaim_span
            stop = highs[index] + config.stop_buffer_atr * atr[index]
        risk_price = (entry - stop) * side
        if risk_price <= 0.0 or not np.isfinite(risk_price):
            used_day.add(day)
            continue
        target = entry + side * config.target_r * risk_price

        fill_index: int | None = None
        expiry = min(index + entry_expiry_bars + 1, len(m15))
        for candidate in range(index + 1, expiry):
            if dates[candidate] != day:
                break
            if lows[candidate] <= entry <= highs[candidate]:
                fill_index = candidate
                break
        used_day.add(day)
        if fill_index is None:
            continue

        exit_index: int | None = None
        gross_r: float | None = None
        state = "TIME_EXIT"
        for candidate in range(fill_index, min(fill_index + max_hold_bars, len(m15))):
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
                gross_r = float(config.target_r)
                state = "WIN"
                break
        if exit_index is None:
            exit_index = min(fill_index + max_hold_bars - 1, len(m15) - 1)
            gross_r = ((closes[exit_index] - entry) * side) / risk_price

        trades.append(
            {
                "config_id": config.config_id,
                "year": int(target_year),
                "signal_at": pd.Timestamp(timestamps[index]).isoformat(),
                "entry_at": pd.Timestamp(timestamps[fill_index]).isoformat(),
                "exit_at": pd.Timestamp(timestamps[exit_index]).isoformat(),
                "direction": "LONG" if side > 0 else "SHORT",
                "asia_high": asia_high,
                "asia_low": asia_low,
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
    shrink = np.sqrt(n / (n + 80.0))
    return float(expectancy * shrink + 0.08 * np.log(min(pf, 3.0)) + 0.06 * (positive_year_ratio - 0.5) - 0.004 * drawdown)

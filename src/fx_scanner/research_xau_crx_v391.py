from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .research_xau_slr_v390 import _resample_ohlc, net_r, summarize_trades

RESEARCH_VERSION = "V391"
ARTIFACT_CONTRACT = "XAU_CRX_RAW_WALKFORWARD_V391_1"
SYMBOL = "XAUUSD"
BASE_COST_PRICE = 0.40
STRESS_COST_PRICE = 0.80
ENTRY_EXPIRY_BARS = 4
MAX_HOLD_BARS = 36
STOP_BUFFER_ATR = 0.10
REACCEL_RANGE_MULT = 1.25
MAX_COMPRESSION_WIDTH_FRACTION = 0.75


@dataclass(frozen=True)
class CRXConfig:
    impulse_bars: int
    compression_bars: int
    impulse_atr_mult: float
    max_retrace_fraction: float
    entry_retrace_fraction: float
    target_r: float

    @property
    def config_id(self) -> str:
        return (
            f"I{self.impulse_bars}_L{self.compression_bars}_A{self.impulse_atr_mult:.2f}_"
            f"M{self.max_retrace_fraction:.2f}_E{self.entry_retrace_fraction:.2f}_T{self.target_r:.1f}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[CRXConfig]:
    return [
        CRXConfig(*values)
        for values in itertools.product(
            (4, 6),
            (3, 5),
            (1.50, 2.00),
            (0.35, 0.55),
            (0.25, 0.40),
            (1.6, 2.0),
        )
    ]


def prepare_m5(price: pd.DataFrame) -> pd.DataFrame:
    m5 = _resample_ohlc(price, "5min")
    previous_close = m5["close"].shift(1)
    tr = pd.concat(
        [
            m5["high"] - m5["low"],
            (m5["high"] - previous_close).abs(),
            (m5["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    m5["tr"] = tr
    m5["atr14"] = tr.rolling(14, min_periods=14).mean()
    m5["bar_range"] = m5["high"] - m5["low"]
    denom = m5["bar_range"].replace(0.0, np.nan)
    m5["body_fraction"] = (m5["close"] - m5["open"]).abs() / denom
    m5["close_position"] = (m5["close"] - m5["low"]) / denom
    return m5.reset_index(drop=True)


def _resolve_exit_bar(*, side: int, low: float, high: float, stop: float, target: float) -> str | None:
    stop_hit = low <= stop if side > 0 else high >= stop
    target_hit = high >= target if side > 0 else low <= target
    if stop_hit:
        return "LOSS"
    if target_hit:
        return "WIN"
    return None


def _signal_arrays(m5: pd.DataFrame, config: CRXConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(m5)
    long_signal = np.zeros(n, dtype=bool)
    short_signal = np.zeros(n, dtype=bool)
    comp_high_out = np.full(n, np.nan)
    comp_low_out = np.full(n, np.nan)

    opens = m5["open"].to_numpy(dtype=float)
    highs = m5["high"].to_numpy(dtype=float)
    lows = m5["low"].to_numpy(dtype=float)
    closes = m5["close"].to_numpy(dtype=float)
    tr = m5["tr"].to_numpy(dtype=float)
    atr = m5["atr14"].to_numpy(dtype=float)
    body_fraction = m5["body_fraction"].to_numpy(dtype=float)
    close_position = m5["close_position"].to_numpy(dtype=float)

    warmup = 20 + config.impulse_bars + config.compression_bars
    for index in range(warmup, n):
        comp_start = index - config.compression_bars
        imp_end = comp_start
        imp_start = imp_end - config.impulse_bars
        if imp_start < 1:
            continue

        reference_atr = atr[imp_start - 1]
        if not np.isfinite(reference_atr) or reference_atr <= 0.0:
            continue

        impulse_start_close = closes[imp_start - 1]
        impulse_end_close = closes[imp_end - 1]
        impulse_move = impulse_end_close - impulse_start_close
        abs_move = abs(impulse_move)
        if abs_move < config.impulse_atr_mult * reference_atr:
            continue

        comp_high = float(np.max(highs[comp_start:index]))
        comp_low = float(np.min(lows[comp_start:index]))
        comp_width = comp_high - comp_low
        if comp_width <= 0.0 or comp_width > MAX_COMPRESSION_WIDTH_FRACTION * abs_move:
            continue

        comp_median_tr = float(np.median(tr[comp_start:index]))
        if not np.isfinite(comp_median_tr) or comp_median_tr <= 0.0:
            continue
        if comp_median_tr > 0.85 * reference_atr:
            continue

        current_range = highs[index] - lows[index]
        if current_range < REACCEL_RANGE_MULT * comp_median_tr:
            continue
        if body_fraction[index] < 0.55:
            continue

        if impulse_move > 0.0:
            max_pullback = impulse_end_close - comp_low
            shallow = max_pullback <= config.max_retrace_fraction * abs_move
            continuation = closes[index] > comp_high and close_position[index] >= 0.72 and closes[index] > opens[index]
            if shallow and continuation:
                long_signal[index] = True
                comp_high_out[index] = comp_high
                comp_low_out[index] = comp_low
        else:
            max_pullback = comp_high - impulse_end_close
            shallow = max_pullback <= config.max_retrace_fraction * abs_move
            continuation = closes[index] < comp_low and close_position[index] <= 0.28 and closes[index] < opens[index]
            if shallow and continuation:
                short_signal[index] = True
                comp_high_out[index] = comp_high
                comp_low_out[index] = comp_low

    return long_signal, short_signal, comp_high_out, comp_low_out


def simulate_config(
    m5: pd.DataFrame,
    config: CRXConfig,
    *,
    target_year: int,
    entry_expiry_bars: int = ENTRY_EXPIRY_BARS,
    max_hold_bars: int = MAX_HOLD_BARS,
) -> list[dict[str, Any]]:
    long_signal, short_signal, comp_high, comp_low = _signal_arrays(m5, config)
    signal_indexes = np.flatnonzero(long_signal | short_signal)

    timestamps = m5["timestamp"].to_numpy()
    highs = m5["high"].to_numpy(dtype=float)
    lows = m5["low"].to_numpy(dtype=float)
    closes = m5["close"].to_numpy(dtype=float)
    atr = m5["atr14"].to_numpy(dtype=float)
    years = m5["timestamp"].dt.year.to_numpy()

    trades: list[dict[str, Any]] = []
    next_allowed = 0
    for index in signal_indexes:
        if index < next_allowed or int(years[index]) != target_year:
            continue
        side = 1 if long_signal[index] else -1
        trigger_range = highs[index] - lows[index]
        if trigger_range <= 0.0 or not np.isfinite(atr[index]) or atr[index] <= 0.0:
            continue

        if side > 0:
            entry = highs[index] - config.entry_retrace_fraction * trigger_range
            stop = min(comp_low[index], lows[index]) - STOP_BUFFER_ATR * atr[index]
        else:
            entry = lows[index] + config.entry_retrace_fraction * trigger_range
            stop = max(comp_high[index], highs[index]) + STOP_BUFFER_ATR * atr[index]
        risk_price = (entry - stop) * side
        if not np.isfinite(risk_price) or risk_price <= 0.0:
            continue
        target = entry + side * config.target_r * risk_price

        fill_index: int | None = None
        for candidate in range(index + 1, min(index + entry_expiry_bars + 1, len(m5))):
            if lows[candidate] <= entry <= highs[candidate]:
                fill_index = candidate
                break
        if fill_index is None:
            continue

        exit_index: int | None = None
        gross_r: float | None = None
        state = "TIME_EXIT"
        for candidate in range(fill_index, min(fill_index + max_hold_bars, len(m5))):
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
            exit_index = min(fill_index + max_hold_bars - 1, len(m5) - 1)
            gross_r = ((closes[exit_index] - entry) * side) / risk_price

        timestamp = pd.Timestamp(timestamps[index])
        trades.append(
            {
                "config_id": config.config_id,
                "year": int(target_year),
                "signal_at": timestamp.isoformat(),
                "entry_at": pd.Timestamp(timestamps[fill_index]).isoformat(),
                "exit_at": pd.Timestamp(timestamps[exit_index]).isoformat(),
                "direction": "LONG" if side > 0 else "SHORT",
                "session_utc_hour": int(timestamp.hour),
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

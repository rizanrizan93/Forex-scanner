from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

RESEARCH_VERSION = "V390"
ARTIFACT_CONTRACT = "XAU_SLR_RAW_WALKFORWARD_V390_1"
SYMBOL = "XAUUSD"
BASE_COST_PRICE = 0.40
STRESS_COST_PRICE = 0.80
MAX_HOLD_BARS = 48
ENTRY_EXPIRY_BARS = 6
STOP_BUFFER_ATR = 0.15


@dataclass(frozen=True)
class SLRConfig:
    compression_bars: int
    compression_ratio: float
    displacement_mult: float
    retrace_fraction: float
    target_r: float
    sweep_required: bool

    @property
    def config_id(self) -> str:
        return (
            f"L{self.compression_bars}_C{self.compression_ratio:.2f}_"
            f"D{self.displacement_mult:.2f}_R{self.retrace_fraction:.2f}_"
            f"T{self.target_r:.1f}_S{int(self.sweep_required)}"
        )

    def payload(self) -> dict[str, Any]:
        return {"config_id": self.config_id, **asdict(self)}


def config_grid() -> list[SLRConfig]:
    return [
        SLRConfig(*values)
        for values in itertools.product(
            (4, 6),
            (0.65, 0.80),
            (1.25, 1.50),
            (0.33, 0.50),
            (1.8, 2.2),
            (False, True),
        )
    ]


def _resample_ohlc(price: pd.DataFrame, rule: str) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(price.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    indexed = price.loc[:, ["timestamp", "open", "high", "low", "close"]].copy()
    indexed["timestamp"] = pd.to_datetime(indexed["timestamp"], utc=True)
    indexed = indexed.sort_values("timestamp").set_index("timestamp")
    out = indexed.resample(rule, label="right", closed="right").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    return out.dropna().reset_index()


def prepare_m5(price: pd.DataFrame) -> pd.DataFrame:
    """Build causal M5 execution features plus last fully closed H1/H4 regimes."""
    m5 = _resample_ohlc(price, "5min")
    h1 = _resample_ohlc(price, "1h")
    h4 = _resample_ohlc(price, "4h")

    for frame in (h1, h4):
        frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
        frame["ema200"] = frame["close"].ewm(span=200, adjust=False).mean()
        frame["bull"] = (frame["ema50"] > frame["ema200"]) & (frame["close"] > frame["ema200"])
        frame["bear"] = (frame["ema50"] < frame["ema200"]) & (frame["close"] < frame["ema200"])

    for frame, prefix in ((h1, "h1"), (h4, "h4")):
        m5 = pd.merge_asof(
            m5.sort_values("timestamp"),
            frame.loc[:, ["timestamp", "bull", "bear"]].sort_values("timestamp"),
            on="timestamp",
            direction="backward",
        )
        m5 = m5.rename(columns={"bull": f"{prefix}_bull", "bear": f"{prefix}_bear"})

    previous_close = m5["close"].shift(1)
    true_range = pd.concat(
        [
            m5["high"] - m5["low"],
            (m5["high"] - previous_close).abs(),
            (m5["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    m5["tr"] = true_range
    m5["atr14"] = true_range.rolling(14, min_periods=14).mean()
    m5["bar_range"] = m5["high"] - m5["low"]
    body = (m5["close"] - m5["open"]).abs()
    denom = m5["bar_range"].replace(0.0, np.nan)
    m5["body_fraction"] = body / denom
    m5["close_position"] = (m5["close"] - m5["low"]) / denom

    prior_low = m5["low"].shift(1).rolling(12, min_periods=12).min()
    prior_high = m5["high"].shift(1).rolling(12, min_periods=12).max()
    m5["sweep_low"] = (m5["low"] < prior_low) & (m5["close"] > prior_low)
    m5["sweep_high"] = (m5["high"] > prior_high) & (m5["close"] < prior_high)
    return m5.reset_index(drop=True)


def _resolve_exit_bar(*, side: int, low: float, high: float, stop: float, target: float) -> str | None:
    """Conservative ambiguity policy: when both can trade in one M5 bar, STOP wins."""
    stop_hit = low <= stop if side > 0 else high >= stop
    target_hit = high >= target if side > 0 else low <= target
    if stop_hit:
        return "LOSS"
    if target_hit:
        return "WIN"
    return None


def simulate_config(
    m5: pd.DataFrame,
    config: SLRConfig,
    *,
    target_year: int,
    max_hold_bars: int = MAX_HOLD_BARS,
    entry_expiry_bars: int = ENTRY_EXPIRY_BARS,
    stop_buffer_atr: float = STOP_BUFFER_ATR,
) -> list[dict[str, Any]]:
    data = m5.copy()
    length = config.compression_bars

    median_tr = data["tr"].shift(1).rolling(length, min_periods=length).median()
    compression_high = data["high"].shift(1).rolling(length, min_periods=length).max()
    compression_low = data["low"].shift(1).rolling(length, min_periods=length).min()
    prior_atr = data["atr14"].shift(1)
    contraction = (median_tr / prior_atr) <= config.compression_ratio
    recent_sweep_low = (
        data["sweep_low"].shift(1).rolling(length, min_periods=1).max().fillna(0).astype(bool)
    )
    recent_sweep_high = (
        data["sweep_high"].shift(1).rolling(length, min_periods=1).max().fillna(0).astype(bool)
    )
    expansion = data["bar_range"] >= config.displacement_mult * median_tr

    long_signal = (
        contraction
        & expansion
        & (data["close"] > compression_high)
        & (data["body_fraction"] >= 0.55)
        & (data["close_position"] >= 0.72)
        & data["h1_bull"].fillna(False)
        & data["h4_bull"].fillna(False)
    )
    short_signal = (
        contraction
        & expansion
        & (data["close"] < compression_low)
        & (data["body_fraction"] >= 0.55)
        & (data["close_position"] <= 0.28)
        & data["h1_bear"].fillna(False)
        & data["h4_bear"].fillna(False)
    )
    if config.sweep_required:
        long_signal &= recent_sweep_low
        short_signal &= recent_sweep_high

    signal_indexes = np.flatnonzero((long_signal | short_signal).to_numpy())
    timestamps = data["timestamp"].to_numpy()
    highs = data["high"].to_numpy(dtype=float)
    lows = data["low"].to_numpy(dtype=float)
    closes = data["close"].to_numpy(dtype=float)
    atr = data["atr14"].to_numpy(dtype=float)
    long_array = long_signal.to_numpy(dtype=bool)
    comp_high = compression_high.to_numpy(dtype=float)
    comp_low = compression_low.to_numpy(dtype=float)
    years = data["timestamp"].dt.year.to_numpy()

    trades: list[dict[str, Any]] = []
    next_allowed = 0
    for index in signal_indexes:
        if index < next_allowed or int(years[index]) != target_year:
            continue
        if not np.isfinite(atr[index]) or atr[index] <= 0.0:
            continue

        side = 1 if bool(long_array[index]) else -1
        trigger_range = max(highs[index] - lows[index], 1e-9)
        if side > 0:
            entry = highs[index] - config.retrace_fraction * trigger_range
            stop = min(comp_low[index], lows[index]) - stop_buffer_atr * atr[index]
        else:
            entry = lows[index] + config.retrace_fraction * trigger_range
            stop = max(comp_high[index], highs[index]) + stop_buffer_atr * atr[index]

        risk_price = (entry - stop) * side
        if not np.isfinite(risk_price) or risk_price <= 0.0:
            continue
        target = entry + side * config.target_r * risk_price

        fill_index: int | None = None
        for candidate in range(index + 1, min(index + entry_expiry_bars + 1, len(data))):
            if lows[candidate] <= entry <= highs[candidate]:
                fill_index = candidate
                break
        if fill_index is None:
            continue

        exit_index: int | None = None
        gross_r: float | None = None
        state = "TIME_EXIT"
        for candidate in range(fill_index, min(fill_index + max_hold_bars, len(data))):
            result = _resolve_exit_bar(
                side=side,
                low=float(lows[candidate]),
                high=float(highs[candidate]),
                stop=float(stop),
                target=float(target),
            )
            if result == "LOSS":
                exit_index = candidate
                gross_r = -1.0
                state = "LOSS"
                break
            if result == "WIN":
                exit_index = candidate
                gross_r = float(config.target_r)
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


def net_r(trade: dict[str, Any], *, cost_price: float) -> float:
    risk = max(float(trade.get("risk_price") or 0.0), 1e-9)
    return float(trade.get("gross_r") or 0.0) - float(cost_price) / risk


def summarize_trades(trades: Sequence[dict[str, Any]], *, cost_price: float) -> dict[str, Any]:
    ordered = sorted(
        (dict(row) for row in trades),
        key=lambda row: (str(row.get("exit_at") or ""), str(row.get("entry_at") or "")),
    )
    returns = [net_r(row, cost_price=cost_price) for row in ordered]
    if not returns:
        return {
            "completed": 0,
            "profit_factor_r": 0.0,
            "expectancy_r": 0.0,
            "win_rate": 0.0,
            "net_r": 0.0,
            "max_drawdown_r": 0.0,
            "gross_profit_r": 0.0,
            "gross_loss_r": 0.0,
        }

    gross_profit = sum(value for value in returns if value > 0.0)
    gross_loss = -sum(value for value in returns if value < 0.0)
    pf = gross_profit / gross_loss if gross_loss > 0.0 else 99.0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return {
        "completed": len(returns),
        "profit_factor_r": float(pf),
        "expectancy_r": float(sum(returns) / len(returns)),
        "win_rate": float(sum(value > 0.0 for value in returns) / len(returns)),
        "net_r": float(sum(returns)),
        "max_drawdown_r": float(max_drawdown),
        "gross_profit_r": float(gross_profit),
        "gross_loss_r": float(gross_loss),
    }


def training_score(metrics: dict[str, Any], *, positive_year_ratio: float) -> float:
    n = int(metrics.get("completed") or 0)
    if n <= 0:
        return -1e9
    pf = max(float(metrics.get("profit_factor_r") or 0.0), 0.01)
    expectancy = float(metrics.get("expectancy_r") or 0.0)
    drawdown = float(metrics.get("max_drawdown_r") or 0.0)
    shrink = math.sqrt(n / (n + 100.0))
    return float(
        expectancy * shrink
        + 0.08 * math.log(min(pf, 3.0))
        + 0.05 * (positive_year_ratio - 0.5)
        - 0.004 * drawdown
    )

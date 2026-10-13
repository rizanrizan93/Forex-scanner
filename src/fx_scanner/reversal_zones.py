"""Causal XAU reversal features. Read-only; deliberately no execution imports.

H1 levels are known before the M5 trigger opens. A probability describes a
confirmed reaction, never an unconditional prediction that a zone must reverse.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np
import pandas as pd

CONTRACT = "RIZAN_XAU_REVERSAL_RESEARCH_10M_V1"
GRID = {
    "side": [1, -1],
    "lookback_h1": [6, 12, 24, 48, 96],
    "half_width_atr": [0.0, 0.1, 0.2, 0.35, 0.5],
    "invalidation_atr": [0.2, 0.35, 0.5, 0.75, 1.0],
    "reaction_atr": [0.5, 0.75, 1.0, 1.5, 2.0],
    "horizon_minutes": [30, 60, 120, 240],
    "wick_fraction": [0.0, 0.1, 0.2, 0.3, 0.4],
    "trend": ["ANY", "ALIGNED", "OPPOSED", "FLAT"],
    "approach_atr": [0.0, 0.5, 1.0, 1.5, 2.0],
    "max_age_hours": [6, 12, 24, 48, 96],
    "session_utc": [0, 6, 12, 18],
}
SHAPE = tuple(len(v) for v in GRID.values())
CONFIGURATIONS = math.prod(SHAPE)


def normalize_bars(raw: Any) -> pd.DataFrame:
    frame = pd.DataFrame(raw).copy()
    if "timestamp" not in frame and "timestamp_utc" in frame:
        frame = frame.rename(columns={"timestamp_utc": "timestamp"})
    required = ["timestamp", "open", "high", "low", "close"]
    if not set(required).issubset(frame.columns):
        raise ValueError("M1 OHLC with timestamp required")
    # Never silently interpret an offset-free timestamp as UTC.
    for value in frame["timestamp"]:
        if pd.Timestamp(value).tzinfo is None:
            raise ValueError("TIMESTAMP_OFFSET_REQUIRED")
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True, errors="raise")
    for column in required[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if not np.isfinite(frame[required[1:]].to_numpy()).all():
        raise ValueError("NONFINITE_OHLC")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("INVALID_OHLC")
    if frame.timestamp.duplicated().any():
        raise ValueError("DUPLICATE_M1_TIMESTAMP")
    return frame[required].sort_values("timestamp").set_index("timestamp")


def closed_features(m1: pd.DataFrame) -> pd.DataFrame:
    """M1 timestamps denote bar opens; feature index denotes M5 close time."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    m5 = m1.resample("5min", label="right", closed="left").agg(agg)
    m5 = m5[m1.close.resample("5min", label="right", closed="left").count() == 5].copy()
    h1 = m1.resample("1h", label="right", closed="left").agg(agg)
    h1 = h1[m1.close.resample("1h", label="right", closed="left").count() >= 45].copy()
    previous = h1.close.shift()
    h1["atr"] = pd.concat([h1.high - h1.low, (h1.high-previous).abs(),
                           (h1.low-previous).abs()], axis=1).max(axis=1).rolling(20).mean()
    ema = h1.close.ewm(span=50, adjust=False, min_periods=50).mean()
    h1["slope"] = (ema - ema.shift(3)) / h1.atr
    hours = h1.index.asi8 / 3.6e12
    for lookback in GRID["lookback_h1"]:
        for side, col, operation in [(1, "low", "min"), (-1, "high", "max")]:
            series = h1[col]
            h1[f"level_{side}_{lookback}"] = getattr(series.rolling(lookback), operation)()
            # Latest equal extreme is used; no future bars are consulted.
            arg = series.rolling(lookback).apply(
                lambda a: len(a)-1-(np.argmin(a[::-1]) if side == 1 else np.argmax(a[::-1])), raw=True)
            positions = np.arange(len(h1)) - lookback + 1 + arg.to_numpy()
            valid = np.isfinite(positions)
            formed = np.full(len(h1), np.nan)
            formed[valid] = hours[positions[valid].astype(int)]
            h1[f"formed_{side}_{lookback}"] = formed
    # As-of BEFORE M5 open, not at its close: zone genuinely pre-existed touch.
    keys = pd.DataFrame({"key": m5.index - pd.Timedelta(minutes=5)}, index=m5.index)
    aligned = pd.merge_asof(keys.reset_index(), h1.reset_index().rename(columns={"timestamp":"key"}),
                            on="key", direction="backward", suffixes=("", "_h1"))
    aligned = aligned.set_index("timestamp")
    for col in [c for c in h1.columns if c not in agg]:
        m5[col] = aligned[col]
    m5["approach_high"] = m5.high.shift().rolling(12).max()
    m5["approach_low"] = m5.low.shift().rolling(12).min()
    m5["year"] = m5.index.year
    m5["session"] = m5.index.hour // 6
    return m5


def base_events(features: pd.DataFrame, side: int, lookback: int, width: float) -> pd.DataFrame:
    f = features.copy()
    level = f[f"level_{side}_{lookback}"]
    span = f.high-f.low
    wick = ((np.minimum(f.open, f.close)-f.low) if side == 1 else
            (f.high-np.maximum(f.open, f.close))) / span.replace(0, np.nan)
    age = f.index.asi8 / 3.6e12 - f[f"formed_{side}_{lookback}"]
    approach = ((f.approach_high-level) if side == 1 else (level-f.approach_low)) / f.atr
    mask = ((f.low <= level+width*f.atr) & (f.high >= level-width*f.atr) &
            (side*(f.close-level) >= 0) & (side*(f.close-f.open) > 0) &
            (f.atr > 0) & (age <= 96) & (age >= 0) & approach.notna() & f.slope.notna())
    out = f.loc[mask, ["close", "atr", "year", "session"]].copy()
    out["level"] = level[mask]
    out["wick_bin"] = np.clip(np.searchsorted(GRID["wick_fraction"], wick[mask], side="right")-1, 0, 4)
    out["approach_bin"] = np.clip(np.searchsorted(GRID["approach_atr"], approach[mask], side="right")-1, 0, 4)
    out["age_bin"] = np.searchsorted(GRID["max_age_hours"], age[mask], side="left")
    slope = side * f.slope[mask]
    out["trend_bin"] = np.where(slope > .05, 0, np.where(slope < -.05, 1, 2))
    return out


def thin_events(events: pd.DataFrame) -> pd.DataFrame:
    """One observation per 4h per base geometry, even for shorter horizons."""
    keep, last = [], -(2**63)
    for i, stamp in enumerate(events.index.asi8):
        if int(stamp)-last >= 240*60*1_000_000_000:
            keep.append(i)
            last = int(stamp)
    return events.iloc[keep]


def config_from_index(index: tuple[int, ...]) -> dict[str, Any]:
    return {name: values[i] for (name, values), i in zip(GRID.items(), index)}


def matches(events: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    trend = config["trend"]
    return ((events.wick_bin >= GRID["wick_fraction"].index(config["wick_fraction"])) &
            (events.approach_bin >= GRID["approach_atr"].index(config["approach_atr"])) &
            (events.age_bin <= GRID["max_age_hours"].index(config["max_age_hours"])) &
            (events.session == config["session_utc"]//6) &
            ((events.trend_bin == ["ALIGNED", "OPPOSED", "FLAT"].index(trend)) if trend != "ANY" else True))

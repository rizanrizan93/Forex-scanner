from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from .demo_xau_supply_demand_atlas_v182 import evaluate_supply_demand_atlas
from .models import Bar

TIMEFRAMES = {
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
}


def _ema(series: pd.Series, span: int) -> float | None:
    if len(series) < span:
        return None
    value = float(series.ewm(span=span, adjust=False).mean().iloc[-1])
    return value if isfinite(value) else None


def _pivot_levels(frame: pd.DataFrame, kind: str) -> list[float]:
    if len(frame) < 5:
        return []
    values = frame["high"] if kind == "HIGH" else frame["low"]
    output: list[float] = []
    for i in range(2, len(frame) - 2):
        center = float(values.iloc[i])
        if kind == "HIGH":
            ok = (
                center > float(values.iloc[i - 1])
                and center >= float(values.iloc[i - 2])
                and center > float(values.iloc[i + 1])
                and center >= float(values.iloc[i + 2])
            )
        else:
            ok = (
                center < float(values.iloc[i - 1])
                and center <= float(values.iloc[i - 2])
                and center < float(values.iloc[i + 1])
                and center <= float(values.iloc[i + 2])
            )
        if ok:
            output.append(center)
    return output


def _structure(frame: pd.DataFrame) -> str:
    sample = frame.tail(120)
    highs = _pivot_levels(sample, "HIGH")
    lows = _pivot_levels(sample, "LOW")
    if len(highs) < 2 or len(lows) < 2:
        return "INSUFFICIENT_SWINGS"
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    return "MIXED_SWINGS"


def _trend_context(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "state": "NO_DATA",
            "ema_stack": "UNKNOWN",
            "market_structure": "UNKNOWN",
        }
    closes = frame["close"].astype(float)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    if None not in {ema20, ema50, ema200}:
        assert ema20 is not None and ema50 is not None and ema200 is not None
        if ema20 > ema50 > ema200:
            stack = "BULL_STACK"
        elif ema20 < ema50 < ema200:
            stack = "BEAR_STACK"
        else:
            stack = "MIXED_STACK"
    else:
        stack = "UNKNOWN"

    latest = frame.iloc[-1]
    rolling = frame.tail(20)
    return {
        "state": "AVAILABLE",
        "last_close": float(latest["close"]),
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "ema_stack": stack,
        "market_structure": _structure(frame),
        "rolling20_high": float(rolling["high"].max()),
        "rolling20_low": float(rolling["low"].min()),
    }


def resample_ohlc(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    frame = m1.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "timestamp" not in frame.columns:
            raise ValueError("M1 frame requires timestamp column/index")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    out = frame.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    return out.dropna()


def _bars_from_frame(frame: pd.DataFrame, timeframe: str) -> tuple[Bar, ...]:
    rows: list[Bar] = []
    for ts, row in frame.iterrows():
        timestamp = ts.to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        rows.append(
            Bar(
                "XAUUSD",
                timeframe,
                timestamp.astimezone(UTC),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                1,
                0.0,
                0.0,
            )
        )
    return tuple(rows)


def event_conditioning(
    m1: pd.DataFrame,
    *,
    event_at: datetime,
    supply_demand_lookback_days: int = 90,
) -> dict[str, Any]:
    if event_at.tzinfo is None:
        raise ValueError("event_at must be timezone-aware")
    event_utc = event_at.astimezone(UTC)
    base = m1.copy()
    if not isinstance(base.index, pd.DatetimeIndex):
        base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)
        base = base.set_index("timestamp")
    base = base.sort_index()
    before = base.loc[base.index < event_utc]
    if before.empty:
        return {
            "state": "NO_PRE_EVENT_PRICE",
            "mtf": {},
            "supply_demand": {},
        }

    mtf_frames: dict[str, pd.DataFrame] = {}
    mtf: dict[str, Any] = {}
    for timeframe, rule in TIMEFRAMES.items():
        frame = resample_ohlc(before, rule)
        mtf_frames[timeframe] = frame
        mtf[timeframe] = _trend_context(frame)

    h4_stack = str(dict(mtf.get("H4") or {}).get("ema_stack") or "UNKNOWN")
    strategic_bias = (
        "LONG" if h4_stack == "BULL_STACK"
        else "SHORT" if h4_stack == "BEAR_STACK"
        else "NEUTRAL"
    )

    m15 = mtf_frames["M15"]
    cutoff = event_utc - timedelta(days=int(supply_demand_lookback_days))
    m15_window = m15.loc[m15.index >= cutoff]
    if len(m15_window) >= 300:
        try:
            atlas = evaluate_supply_demand_atlas(
                _bars_from_frame(m15_window, "M15"),
                as_of=event_utc,
                strategic_bias=strategic_bias,
            )
        except Exception as exc:
            atlas = {
                "state": "ATLAS_ERROR",
                "error": f"{type(exc).__name__}:{exc}",
                "execution_influence": False,
                "execution_authority": False,
            }
    else:
        atlas = {
            "state": "INSUFFICIENT_M15_FOR_ATLAS",
            "execution_influence": False,
            "execution_authority": False,
        }

    active_path = dict(dict(atlas.get("path_map") or {}).get("active_path") or {})
    source_zone = dict(active_path.get("source_zone") or {})
    return {
        "state": "AVAILABLE",
        "strategic_bias_proxy": strategic_bias,
        "mtf": mtf,
        "supply_demand": {
            "state": atlas.get("state"),
            "nearest_demand": atlas.get("nearest_demand"),
            "nearest_supply": atlas.get("nearest_supply"),
            "active_reaction_direction": active_path.get("reaction_direction"),
            "active_source_zone": source_zone,
            "source_timeframe": source_zone.get("timeframe"),
            "source_freshness": dict(source_zone.get("lifecycle") or {}).get("freshness"),
            "execution_influence": False,
            "execution_authority": False,
        },
        "execution_influence": False,
        "execution_authority": False,
    }

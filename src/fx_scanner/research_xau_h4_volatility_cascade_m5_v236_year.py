from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .research_xau_zone_reversal_depth_v225 import _load_price_frame

RESEARCH_VERSION = "XAU_H4_VOLATILITY_CASCADE_M5_V236_1"
ARTIFACT_CONTRACT = "XAU_H4_VOLATILITY_CASCADE_M5_YEAR_V236_1"

M5_CONFIRM_BARS = 6
MAX_HOLD_MINUTES = 16 * 60
STOP_BUFFER_ATR = 0.15
TARGET_R = 2.0
MIN_M15_BODY_ATR = 0.55
MIN_CLOSE_LOCATION = 0.68
MIN_RISK_ATR = 0.50

VARIANTS = (
    {"variant_id": "V236_M5_RETEST_HOLD_R2", "m5_mode": "RETEST_HOLD"},
    {"variant_id": "V236_M5_RETEST_DISP_R2", "m5_mode": "RETEST_DISPLACEMENT"},
)


def _year() -> int:
    value = int(os.getenv("XAU_V236_YEAR", "0") or 0)
    if value < 2012 or value > 2026:
        raise SystemExit(f"XAU_V236_YEAR_INVALID:{value}")
    return value


def _aggregate(frame: pd.DataFrame, rule: str, minutes: int) -> pd.DataFrame:
    out = (
        frame.set_index("timestamp")
        .resample(rule, label="left", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            source_rows=("close", "count"),
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    out["close_at"] = out["timestamp"] + pd.to_timedelta(minutes, unit="m")
    return out


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev).abs(),
            (frame["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _context(price: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    m5 = _aggregate(price, "5min", 5)
    m15 = _aggregate(price, "15min", 15)
    h1 = _aggregate(price, "1h", 60)
    h4 = _aggregate(price, "4h", 240)

    for frame in (m5, m15, h1, h4):
        frame["atr14"] = _atr(frame, 14)

    h4["ema20"] = _ema(h4["close"], 20)
    h4["ema50"] = _ema(h4["close"], 50)
    h4["atr_median60_prior"] = h4["atr14"].shift(1).rolling(60, min_periods=60).median()
    h4["direction"] = "NEUTRAL"
    h4_long = (
        (h4["ema20"] > h4["ema50"])
        & (h4["close"] > h4["ema20"])
        & (h4["ema20"] > h4["ema20"].shift(2))
        & (h4["atr14"] > h4["atr_median60_prior"])
    )
    h4_short = (
        (h4["ema20"] < h4["ema50"])
        & (h4["close"] < h4["ema20"])
        & (h4["ema20"] < h4["ema20"].shift(2))
        & (h4["atr14"] > h4["atr_median60_prior"])
    )
    h4.loc[h4_long, "direction"] = "LONG"
    h4.loc[h4_short, "direction"] = "SHORT"

    h1["ema20"] = _ema(h1["close"], 20)
    h1["ema50"] = _ema(h1["close"], 50)
    h1["direction"] = "NEUTRAL"
    h1.loc[
        (h1["ema20"] > h1["ema50"]) & (h1["close"] > h1["ema20"]),
        "direction",
    ] = "LONG"
    h1.loc[
        (h1["ema20"] < h1["ema50"]) & (h1["close"] < h1["ema20"]),
        "direction",
    ] = "SHORT"

    # Prior completed UTC-day external liquidity levels.
    m15["utc_date"] = m15["timestamp"].dt.floor("D")
    daily = (
        m15.groupby("utc_date", as_index=False)
        .agg(day_high=("high", "max"), day_low=("low", "min"))
        .sort_values("utc_date")
    )
    daily["pdh"] = daily["day_high"].shift(1)
    daily["pdl"] = daily["day_low"].shift(1)
    m15 = m15.merge(daily[["utc_date", "pdh", "pdl"]], on="utc_date", how="left")
    m15["prior6_low"] = m15["low"].shift(1).rolling(6, min_periods=6).min()
    m15["prior6_high"] = m15["high"].shift(1).rolling(6, min_periods=6).max()
    m15["prev_close"] = m15["close"].shift(1)

    m5["body"] = (m5["close"] - m5["open"]).abs()
    span = (m5["high"] - m5["low"]).replace(0.0, np.nan)
    m5["close_loc"] = (m5["close"] - m5["low"]) / span

    return m5, m15, h1, h4


def _attach_context(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    work = m15.sort_values("close_at").copy()
    h1_ctx = h1[["close_at", "direction"]].rename(columns={"direction": "h1_direction"})
    h4_ctx = h4[["close_at", "direction"]].rename(columns={"direction": "h4_direction"})
    work = pd.merge_asof(
        work,
        h1_ctx.sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    work = pd.merge_asof(
        work,
        h4_ctx.sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return work


def _m15_cascade(row: pd.Series) -> str | None:
    atr = float(row["atr14"]) if pd.notna(row["atr14"]) else np.nan
    if not np.isfinite(atr) or atr <= 0 or pd.isna(row["pdh"]) or pd.isna(row["pdl"]):
        return None
    rng = max(float(row["high"]) - float(row["low"]), 1e-12)
    body_atr = abs(float(row["close"]) - float(row["open"])) / atr
    close_loc = (float(row["close"]) - float(row["low"])) / rng

    long_break = (
        row["h4_direction"] == "LONG"
        and row["h1_direction"] == "LONG"
        and float(row["prev_close"]) <= float(row["pdh"])
        and float(row["close"]) > float(row["pdh"])
        and body_atr >= MIN_M15_BODY_ATR
        and close_loc >= MIN_CLOSE_LOCATION
    )
    short_break = (
        row["h4_direction"] == "SHORT"
        and row["h1_direction"] == "SHORT"
        and float(row["prev_close"]) >= float(row["pdl"])
        and float(row["close"]) < float(row["pdl"])
        and body_atr >= MIN_M15_BODY_ATR
        and close_loc <= 1.0 - MIN_CLOSE_LOCATION
    )
    if long_break:
        return "LONG"
    if short_break:
        return "SHORT"
    return None


def _m5_retest(row: pd.Series, *, direction: str, level: float, mode: str) -> bool:
    atr = float(row["atr14"]) if pd.notna(row["atr14"]) else np.nan
    if direction == "LONG":
        base = (
            float(row["low"]) <= level
            and float(row["close"]) > level
            and float(row["close"]) > float(row["open"])
        )
        displacement = (
            base
            and np.isfinite(atr)
            and atr > 0
            and float(row["body"]) >= 0.50 * atr
            and float(row["close_loc"]) >= 0.65
        )
    else:
        base = (
            float(row["high"]) >= level
            and float(row["close"]) < level
            and float(row["close"]) < float(row["open"])
        )
        displacement = (
            base
            and np.isfinite(atr)
            and atr > 0
            and float(row["body"]) >= 0.50 * atr
            and float(row["close_loc"]) <= 0.35
        )
    return bool(displacement if mode == "RETEST_DISPLACEMENT" else base)


def _resolve_m1(
    price: pd.DataFrame,
    *,
    entry_at: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    timestamps = price["timestamp"].to_numpy(dtype="datetime64[ns]")
    start = int(np.searchsorted(timestamps, np.datetime64(entry_at.to_datetime64()), side="left"))
    deadline = entry_at + pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    end = int(np.searchsorted(timestamps, np.datetime64(deadline.to_datetime64()), side="right"))
    end = min(end, len(price))
    if start >= end:
        return {"exit_reason": "NO_HORIZON", "gross_points": None}

    for idx in range(start, end):
        row = price.iloc[idx]
        if direction == "LONG":
            sl_hit = float(row["low"]) <= stop
            tp_hit = float(row["high"]) >= target
        else:
            sl_hit = float(row["high"]) >= stop
            tp_hit = float(row["low"]) <= target
        if sl_hit:
            pnl = stop - entry if direction == "LONG" else entry - stop
            return {
                "exit_reason": "SL_ENTRY_BAR_CONSERVATIVE" if idx == start else "SL",
                "exit_at": pd.Timestamp(row["timestamp"]).isoformat(),
                "exit_price": stop,
                "gross_points": pnl,
            }
        if idx > start and tp_hit:
            pnl = target - entry if direction == "LONG" else entry - target
            return {
                "exit_reason": "TP",
                "exit_at": pd.Timestamp(row["timestamp"]).isoformat(),
                "exit_price": target,
                "gross_points": pnl,
            }

    last = price.iloc[end - 1]
    exit_price = float(last["close"])
    pnl = exit_price - entry if direction == "LONG" else entry - exit_price
    return {
        "exit_reason": "TIME_EXIT_16H",
        "exit_at": pd.Timestamp(last["timestamp"]).isoformat(),
        "exit_price": exit_price,
        "gross_points": pnl,
    }


def generate_year(price: pd.DataFrame, *, year: int) -> dict[str, Any]:
    m5, m15, h1, h4 = _context(price)
    m15 = _attach_context(m15, h1, h4)
    m5_close = m5["close_at"].to_numpy(dtype="datetime64[ns]")

    diagnostics = {
        variant["variant_id"]: {
            "m15_cascades": 0,
            "m5_confirmed": 0,
            "valid_geometry": 0,
            "year_fills": 0,
        }
        for variant in VARIANTS
    }
    trades: list[dict[str, Any]] = []

    for _, row in m15.iterrows():
        direction = _m15_cascade(row)
        if direction is None:
            continue
        level = float(row["pdh"] if direction == "LONG" else row["pdl"])
        setup_close = pd.Timestamp(row["close_at"])
        start = int(
            np.searchsorted(
                m5_close,
                np.datetime64(setup_close.to_datetime64()),
                side="right",
            )
        )
        stop_search = min(len(m5), start + M5_CONFIRM_BARS)

        for variant in VARIANTS:
            variant_id = str(variant["variant_id"])
            diagnostics[variant_id]["m15_cascades"] += 1
            trigger_idx: int | None = None
            for idx in range(start, stop_search):
                if _m5_retest(
                    m5.iloc[idx],
                    direction=direction,
                    level=level,
                    mode=str(variant["m5_mode"]),
                ):
                    trigger_idx = idx
                    break
            if trigger_idx is None or trigger_idx + 1 >= len(m5):
                continue
            diagnostics[variant_id]["m5_confirmed"] += 1

            entry_row = m5.iloc[trigger_idx + 1]
            fill_at = pd.Timestamp(entry_row["timestamp"])
            if fill_at.year != year:
                continue
            entry = float(entry_row["open"])
            atr = float(row["atr14"])
            if direction == "LONG":
                stop = float(row["prior6_low"]) - STOP_BUFFER_ATR * atr
                risk = entry - stop
                target = entry + TARGET_R * risk
            else:
                stop = float(row["prior6_high"]) + STOP_BUFFER_ATR * atr
                risk = stop - entry
                target = entry - TARGET_R * risk

            if (
                not np.isfinite(risk)
                or risk <= 0
                or risk < MIN_RISK_ATR * atr
                or stop <= 0
                or target <= 0
            ):
                continue
            diagnostics[variant_id]["valid_geometry"] += 1

            outcome = _resolve_m1(
                price,
                entry_at=fill_at,
                entry=entry,
                stop=stop,
                target=target,
                direction=direction,
            )
            if outcome.get("gross_points") is None:
                continue
            diagnostics[variant_id]["year_fills"] += 1
            trades.append(
                {
                    "year": year,
                    "variant_id": variant_id,
                    "family": "H4_VOL_EXPANSION_H1_PD_CASCADE_M5",
                    "direction": direction,
                    "setup_at": setup_close.isoformat(),
                    "m5_trigger_at": pd.Timestamp(m5.iloc[trigger_idx]["close_at"]).isoformat(),
                    "fill_at": fill_at.isoformat(),
                    "external_level": level,
                    "entry": entry,
                    "sl": stop,
                    "tp": target,
                    "risk_points": risk,
                    "rr": TARGET_R,
                    "margin_usd_1_to_100": entry / 100.0,
                    "exit_reason": outcome["exit_reason"],
                    "exit_at": outcome["exit_at"],
                    "exit_price": outcome["exit_price"],
                    "gross_points": float(outcome["gross_points"]),
                    "gross_pnl_usd": float(outcome["gross_points"]),
                    "fixed_lot_reference": 0.01,
                }
            )

    trades.sort(key=lambda row: (row["fill_at"], row["variant_id"], row["direction"]))
    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "year": year,
        "architecture": {
            "H4": "EMA20_50_TREND_PLUS_ATR14_ABOVE_PRIOR_60_H4_MEDIAN",
            "H1": "EMA20_50_DIRECTIONAL_ALIGNMENT",
            "M15": "FIRST_CLOSE_THROUGH_PDH_PDL_BODY_GTE_0_55_ATR_CLOSE_LOCATION_0_68",
            "M5": "RETEST_AND_HOLD_EXTERNAL_LEVEL_WITH_OPTIONAL_DISPLACEMENT",
            "entry": "NEXT_M5_OPEN_AFTER_COMPLETED_RETEST",
            "stop": "PRIOR_6_M15_EXTREME_PLUS_0_15_ATR",
            "minimum_risk": "0.50_M15_ATR",
            "target": "2R",
            "max_hold": "16H",
        },
        "variants": list(VARIANTS),
        "diagnostics": diagnostics,
        "trades": trades,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    year = _year()
    price_path = os.getenv("XAU_V236_PRICE_CSV", f"/tmp/histdata/xau-v236-{year}.csv")
    output = Path(
        os.getenv(
            "XAU_V236_OUTPUT",
            f"artifacts/xau-h4-volatility-cascade-m5-v236-{year}.json",
        )
    )
    result = generate_year(_load_price_frame(price_path), year=year)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_V236_YEAR "
        f"year={year} trades={len(result['trades'])} authority=SHADOW_ONLY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

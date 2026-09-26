from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RESEARCH_VERSION = "XAU_H4_H1_M15_M5_BREAKOUT_RETEST_V234_1"
ARTIFACT_CONTRACT = "XAU_H4_H1_M15_M5_BREAKOUT_RETEST_YEAR_V234_1"

M5_RETEST_WINDOW_BARS = 6
STOP_BUFFER_ATR = 0.15
MIN_RISK_ATR = 0.50

VARIANTS = (
    {
        "variant_id": "V234_L12_M5_RETEST_R15",
        "lookback": 12,
        "target_r": 1.50,
        "cooldown_m15_bars": 3,
    },
    {
        "variant_id": "V234_L20_M5_RETEST_R20",
        "lookback": 20,
        "target_r": 2.00,
        "cooldown_m15_bars": 4,
    },
)


def _year() -> int:
    value = int(os.getenv("XAU_V234_YEAR", "0") or 0)
    if value < 2012 or value > 2026:
        raise SystemExit(f"XAU_V234_YEAR_INVALID:{value}")
    return value


def _load_m1(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V234_M1_COLUMNS_MISSING:{sorted(missing)}")
    out = frame.loc[:, ["timestamp", "open", "high", "low", "close"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = (
        out.dropna()
        .sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise RuntimeError("V234_M1_EMPTY")
    return out


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
    previous = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _bars_since(mask: pd.Series) -> pd.Series:
    output = np.full(len(mask), np.inf, dtype=float)
    last: int | None = None
    for index, value in enumerate(mask.fillna(False).astype(bool).tolist()):
        if value:
            last = index
            output[index] = 0.0
        elif last is not None:
            output[index] = float(index - last)
    return pd.Series(output, index=mask.index)


def _prepare(m1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    m5 = _aggregate(m1, "5min", 5)
    m15 = _aggregate(m1, "15min", 15)
    h1 = _aggregate(m1, "1h", 60)
    h4 = _aggregate(m1, "4h", 240)

    for frame in (m5, m15, h1, h4):
        frame["atr14"] = _atr(frame, 14)

    h4["ema20"] = _ema(h4["close"], 20)
    h4["ema50"] = _ema(h4["close"], 50)
    h4["ema200"] = _ema(h4["close"], 200)
    h4["direction"] = "NEUTRAL"
    h4_long = (
        (h4["ema20"] > h4["ema50"])
        & (h4["ema50"] > h4["ema200"])
        & (h4["close"] > h4["ema20"])
        & (h4["ema20"] > h4["ema20"].shift(2))
    )
    h4_short = (
        (h4["ema20"] < h4["ema50"])
        & (h4["ema50"] < h4["ema200"])
        & (h4["close"] < h4["ema20"])
        & (h4["ema20"] < h4["ema20"].shift(2))
    )
    h4.loc[h4_long, "direction"] = "LONG"
    h4.loc[h4_short, "direction"] = "SHORT"

    h1["ema20"] = _ema(h1["close"], 20)
    h1["ema50"] = _ema(h1["close"], 50)
    h1["prior12_high"] = h1["high"].shift(1).rolling(12, min_periods=12).max()
    h1["prior12_low"] = h1["low"].shift(1).rolling(12, min_periods=12).min()
    h1["bos_long"] = h1["close"] > h1["prior12_high"]
    h1["bos_short"] = h1["close"] < h1["prior12_low"]
    h1["since_bos_long"] = _bars_since(h1["bos_long"])
    h1["since_bos_short"] = _bars_since(h1["bos_short"])
    h1["permission"] = "NEUTRAL"
    h1.loc[
        (h1["ema20"] > h1["ema50"])
        & (h1["close"] > h1["ema20"])
        & (h1["since_bos_long"] <= 8),
        "permission",
    ] = "LONG"
    h1.loc[
        (h1["ema20"] < h1["ema50"])
        & (h1["close"] < h1["ema20"])
        & (h1["since_bos_short"] <= 8),
        "permission",
    ] = "SHORT"

    m15["body"] = (m15["close"] - m15["open"]).abs()
    span = (m15["high"] - m15["low"]).replace(0.0, np.nan)
    m15["close_loc"] = (m15["close"] - m15["low"]) / span
    m15["local6_low"] = m15["low"].rolling(6, min_periods=6).min()
    m15["local6_high"] = m15["high"].rolling(6, min_periods=6).max()
    for lookback in (12, 20):
        m15[f"prior{lookback}_high"] = (
            m15["high"].shift(1).rolling(lookback, min_periods=lookback).max()
        )
        m15[f"prior{lookback}_low"] = (
            m15["low"].shift(1).rolling(lookback, min_periods=lookback).min()
        )

    return m5, m15, h1, h4


def _attach_context(m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> pd.DataFrame:
    left = m15.sort_values("close_at").copy()
    left = pd.merge_asof(
        left,
        h1.loc[:, ["close_at", "permission"]]
        .rename(columns={"permission": "h1_permission"})
        .sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    left = pd.merge_asof(
        left,
        h4.loc[:, ["close_at", "direction"]]
        .rename(columns={"direction": "h4_direction"})
        .sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return left


def _breakout(
    row: pd.Series,
    *,
    direction: str,
    lookback: int,
) -> tuple[bool, float | None]:
    atr = float(row["atr14"]) if pd.notna(row["atr14"]) else np.nan
    if not np.isfinite(atr) or atr <= 0:
        return False, None
    if direction == "LONG":
        level = row[f"prior{lookback}_high"]
        passed = bool(
            pd.notna(level)
            and row["h4_direction"] == "LONG"
            and row["h1_permission"] == "LONG"
            and float(row["close"]) > float(level)
            and float(row["body"]) >= 0.55 * atr
            and float(row["close_loc"]) >= 0.68
        )
    else:
        level = row[f"prior{lookback}_low"]
        passed = bool(
            pd.notna(level)
            and row["h4_direction"] == "SHORT"
            and row["h1_permission"] == "SHORT"
            and float(row["close"]) < float(level)
            and float(row["body"]) >= 0.55 * atr
            and float(row["close_loc"]) <= 0.32
        )
    return passed, None if pd.isna(level) else float(level)


def _find_retest(
    m5: pd.DataFrame,
    *,
    signal_close: pd.Timestamp,
    level: float,
    direction: str,
) -> int | None:
    close_ns = m5["close_at"].to_numpy(dtype="datetime64[ns]")
    start = int(
        np.searchsorted(
            close_ns,
            np.datetime64(signal_close.to_datetime64()),
            side="right",
        )
    )
    stop = min(len(m5), start + M5_RETEST_WINDOW_BARS)
    for idx in range(start, stop):
        row = m5.iloc[idx]
        if direction == "LONG":
            passed = (
                float(row["low"]) <= level
                and float(row["close"]) > level
                and float(row["close"]) > float(row["open"])
            )
        else:
            passed = (
                float(row["high"]) >= level
                and float(row["close"]) < level
                and float(row["close"]) < float(row["open"])
            )
        if passed:
            return idx
    return None


def _resolve(
    m1: pd.DataFrame,
    *,
    entry_at: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    timestamps = m1["timestamp"].to_numpy(dtype="datetime64[ns]")
    start = int(
        np.searchsorted(
            timestamps,
            np.datetime64(entry_at.to_datetime64()),
            side="left",
        )
    )
    if start >= len(m1):
        return {"status": "NO_M1_ENTRY_BAR"}

    deadline = entry_at + pd.Timedelta(minutes=240)
    end = int(
        np.searchsorted(
            timestamps,
            np.datetime64(deadline.to_datetime64()),
            side="right",
        )
    )
    end = min(end, len(m1))
    if end <= start:
        return {"status": "NO_M1_HORIZON"}

    for idx in range(start, end):
        row = m1.iloc[idx]
        if direction == "LONG":
            sl_hit = float(row["low"]) <= stop
            tp_hit = float(row["high"]) >= target
        else:
            sl_hit = float(row["high"]) >= stop
            tp_hit = float(row["low"]) <= target
        if sl_hit:
            gross = stop - entry if direction == "LONG" else entry - stop
            return {
                "status": "SL_ENTRY_BAR_CONSERVATIVE" if idx == start else "SL",
                "exit_at": pd.Timestamp(row["timestamp"]).isoformat(),
                "exit_price": stop,
                "gross_points": gross,
            }
        if idx > start and tp_hit:
            gross = target - entry if direction == "LONG" else entry - target
            return {
                "status": "TP",
                "exit_at": pd.Timestamp(row["timestamp"]).isoformat(),
                "exit_price": target,
                "gross_points": gross,
            }

    last = m1.iloc[end - 1]
    exit_price = float(last["close"])
    gross = exit_price - entry if direction == "LONG" else entry - exit_price
    return {
        "status": "TIME_EXIT_4H",
        "exit_at": pd.Timestamp(last["timestamp"]).isoformat(),
        "exit_price": exit_price,
        "gross_points": gross,
    }


def generate_year(m1: pd.DataFrame, *, year: int) -> dict[str, Any]:
    m5, m15, h1, h4 = _prepare(m1)
    m15 = _attach_context(m15, h1, h4)
    trades: list[dict[str, Any]] = []
    diagnostics: dict[str, dict[str, int]] = {
        str(variant["variant_id"]): {
            "breakouts": 0,
            "m5_retests": 0,
            "valid_geometry": 0,
            "fills": 0,
        }
        for variant in VARIANTS
    }

    for variant in VARIANTS:
        variant_id = str(variant["variant_id"])
        lookback = int(variant["lookback"])
        target_r = float(variant["target_r"])
        cooldown = pd.Timedelta(minutes=15 * int(variant["cooldown_m15_bars"]))
        last_fill: dict[str, pd.Timestamp | None] = {"LONG": None, "SHORT": None}

        for _, row in m15.iterrows():
            if (
                pd.isna(row.get("h4_direction"))
                or pd.isna(row.get("h1_permission"))
                or pd.isna(row.get("atr14"))
            ):
                continue
            direction: str | None = None
            level: float | None = None
            long_pass, long_level = _breakout(row, direction="LONG", lookback=lookback)
            short_pass, short_level = _breakout(row, direction="SHORT", lookback=lookback)
            if long_pass:
                direction, level = "LONG", long_level
            elif short_pass:
                direction, level = "SHORT", short_level
            if direction is None or level is None:
                continue

            diagnostics[variant_id]["breakouts"] += 1
            signal_close = pd.Timestamp(row["close_at"])
            retest_index = _find_retest(
                m5,
                signal_close=signal_close,
                level=level,
                direction=direction,
            )
            if retest_index is None or retest_index + 1 >= len(m5):
                continue
            diagnostics[variant_id]["m5_retests"] += 1

            entry_row = m5.iloc[retest_index + 1]
            fill_at = pd.Timestamp(entry_row["timestamp"])
            if fill_at.year != year:
                continue
            if last_fill[direction] is not None and fill_at < last_fill[direction] + cooldown:
                continue

            entry = float(entry_row["open"])
            atr = float(row["atr14"])
            if direction == "LONG":
                stop = float(row["local6_low"]) - STOP_BUFFER_ATR * atr
                risk = entry - stop
                target = entry + target_r * risk
            else:
                stop = float(row["local6_high"]) + STOP_BUFFER_ATR * atr
                risk = stop - entry
                target = entry - target_r * risk
            if (
                not np.isfinite(risk)
                or risk < MIN_RISK_ATR * atr
                or stop <= 0
                or target <= 0
            ):
                continue
            diagnostics[variant_id]["valid_geometry"] += 1

            outcome = _resolve(
                m1,
                entry_at=fill_at,
                entry=entry,
                stop=stop,
                target=target,
                direction=direction,
            )
            if outcome.get("gross_points") is None:
                continue
            diagnostics[variant_id]["fills"] += 1
            last_fill[direction] = fill_at
            trades.append(
                {
                    "year": year,
                    "variant_id": variant_id,
                    "family": "H4_H1_M15_BREAKOUT_M5_RETEST",
                    "direction": direction,
                    "lookback": lookback,
                    "target_r": target_r,
                    "breakout_level": level,
                    "signal_at": signal_close.isoformat(),
                    "retest_at": pd.Timestamp(m5.iloc[retest_index]["close_at"]).isoformat(),
                    "fill_at": fill_at.isoformat(),
                    "entry": entry,
                    "sl": stop,
                    "tp": target,
                    "risk_points": risk,
                    "rr": target_r,
                    "margin_usd_1_to_100": entry / 100.0,
                    "exit_reason": outcome["status"],
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
            "H4": "EMA20_50_200_STACK_PLUS_EMA20_SLOPE_DIRECTION_AUTHORITY",
            "H1": "EMA20_50_PLUS_12_BAR_BOS_WITHIN_8_H1_BARS",
            "M15": "FROZEN_STYLE_L12_OR_L20_BREAKOUT_DISPLACEMENT",
            "M5": "BREAKOUT_LEVEL_RETEST_AND_DIRECTIONAL_CLOSE_THEN_NEXT_M5_OPEN",
            "stop": "M15_LOCAL6_PLUS_0_15_ATR",
            "minimum_risk": "0.50_ATR",
            "target": "L12_1.5R_L20_2.0R",
            "max_hold": "16_M15_BARS_4H",
        },
        "variants": list(VARIANTS),
        "trades": trades,
        "diagnostics": diagnostics,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    year = _year()
    price_path = os.getenv(
        "XAU_V234_PRICE_CSV",
        f"/tmp/histdata/xau-v234-{year}.csv",
    )
    output = Path(
        os.getenv(
            "XAU_V234_OUTPUT",
            f"artifacts/xau-h4-h1-m15-m5-breakout-v234-{year}.json",
        )
    )
    result = generate_year(_load_m1(price_path), year=year)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_V234_YEAR "
        f"year={year} trades={len(result['trades'])} "
        f"variants={len(VARIANTS)} authority=SHADOW_ONLY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

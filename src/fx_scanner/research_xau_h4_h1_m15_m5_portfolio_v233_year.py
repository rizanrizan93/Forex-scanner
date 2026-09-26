from __future__ import annotations

import json
import os
from datetime import UTC
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

RESEARCH_VERSION = "XAU_H4_H1_M15_M5_CONTINUATION_V233_1"
ARTIFACT_CONTRACT = "XAU_H4_H1_M15_M5_CONTINUATION_YEAR_V233_1"

TARGET_R = 2.0
M5_TRIGGER_WINDOW_BARS = 6
MAX_HOLD_MINUTES = 16 * 60
COOLDOWN_MINUTES = 60
STOP_BUFFER_ATR = 0.10

VARIANTS = (
    {
        "variant_id": "V233_PB20_BASIC_R2",
        "pullback_ema": 20,
        "trigger_mode": "BASIC_BREAK",
    },
    {
        "variant_id": "V233_PB50_BASIC_R2",
        "pullback_ema": 50,
        "trigger_mode": "BASIC_BREAK",
    },
    {
        "variant_id": "V233_PB20_DISP_R2",
        "pullback_ema": 20,
        "trigger_mode": "DISPLACEMENT_BREAK",
    },
    {
        "variant_id": "V233_PB50_DISP_R2",
        "pullback_ema": 50,
        "trigger_mode": "DISPLACEMENT_BREAK",
    },
)


def _year() -> int:
    value = int(os.getenv("XAU_V233_YEAR", "0") or 0)
    if value < 2012 or value > 2026:
        raise SystemExit(f"XAU_V233_YEAR_INVALID:{value}")
    return value


def _load_m1(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"V233_M1_COLUMNS_MISSING:{sorted(missing)}")
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
        raise RuntimeError("V233_M1_EMPTY")
    return out


def _aggregate(frame: pd.DataFrame, rule: str, minutes: int) -> pd.DataFrame:
    indexed = frame.set_index("timestamp")
    out = (
        indexed.resample(rule, label="left", closed="left")
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


def _prepare_htf(m1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    long_mask = (
        (h4["ema20"] > h4["ema50"])
        & (h4["ema50"] > h4["ema200"])
        & (h4["close"] > h4["ema20"])
        & (h4["ema20"] > h4["ema20"].shift(2))
    )
    short_mask = (
        (h4["ema20"] < h4["ema50"])
        & (h4["ema50"] < h4["ema200"])
        & (h4["close"] < h4["ema20"])
        & (h4["ema20"] < h4["ema20"].shift(2))
    )
    h4.loc[long_mask, "direction"] = "LONG"
    h4.loc[short_mask, "direction"] = "SHORT"

    h1["ema20"] = _ema(h1["close"], 20)
    h1["ema50"] = _ema(h1["close"], 50)
    h1["prior12_high"] = h1["high"].shift(1).rolling(12, min_periods=12).max()
    h1["prior12_low"] = h1["low"].shift(1).rolling(12, min_periods=12).min()
    h1["bos_long"] = h1["close"] > h1["prior12_high"]
    h1["bos_short"] = h1["close"] < h1["prior12_low"]
    h1["since_bos_long"] = _bars_since(h1["bos_long"])
    h1["since_bos_short"] = _bars_since(h1["bos_short"])
    h1["permission"] = "NEUTRAL"
    h1_long = (
        (h1["ema20"] > h1["ema50"])
        & (h1["close"] > h1["ema20"])
        & (h1["since_bos_long"] <= 8)
    )
    h1_short = (
        (h1["ema20"] < h1["ema50"])
        & (h1["close"] < h1["ema20"])
        & (h1["since_bos_short"] <= 8)
    )
    h1.loc[h1_long, "permission"] = "LONG"
    h1.loc[h1_short, "permission"] = "SHORT"

    m15["ema20"] = _ema(m15["close"], 20)
    m15["ema50"] = _ema(m15["close"], 50)
    m15["structural_low"] = m15["low"].rolling(4, min_periods=4).min()
    m15["structural_high"] = m15["high"].rolling(4, min_periods=4).max()

    m5["prev3_high"] = m5["high"].shift(1).rolling(3, min_periods=3).max()
    m5["prev3_low"] = m5["low"].shift(1).rolling(3, min_periods=3).min()
    m5["body"] = (m5["close"] - m5["open"]).abs()
    span = (m5["high"] - m5["low"]).replace(0.0, np.nan)
    m5["close_loc"] = (m5["close"] - m5["low"]) / span
    return m5, m15, h1, h4


def _attach_completed_context(
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    h4: pd.DataFrame,
) -> pd.DataFrame:
    left = m15.sort_values("close_at").copy()
    h1_ctx = h1.loc[:, ["close_at", "permission", "atr14"]].rename(
        columns={"permission": "h1_permission", "atr14": "h1_atr14"}
    )
    h4_ctx = h4.loc[:, ["close_at", "direction", "atr14"]].rename(
        columns={"direction": "h4_direction", "atr14": "h4_atr14"}
    )
    left = pd.merge_asof(
        left,
        h1_ctx.sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    left = pd.merge_asof(
        left,
        h4_ctx.sort_values("close_at"),
        on="close_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return left


def _setup_pass(row: pd.Series, *, direction: str, pullback_ema: int) -> bool:
    ema = float(row[f"ema{pullback_ema}"])
    ema20 = float(row["ema20"])
    ema50 = float(row["ema50"])
    if not np.isfinite(ema) or not np.isfinite(float(row["atr14"])):
        return False
    if direction == "LONG":
        return bool(
            row["h4_direction"] == "LONG"
            and row["h1_permission"] == "LONG"
            and ema20 > ema50
            and float(row["low"]) <= ema
            and float(row["close"]) > ema
            and float(row["close"]) > ema20
            and float(row["close"]) > float(row["open"])
        )
    return bool(
        row["h4_direction"] == "SHORT"
        and row["h1_permission"] == "SHORT"
        and ema20 < ema50
        and float(row["high"]) >= ema
        and float(row["close"]) < ema
        and float(row["close"]) < ema20
        and float(row["close"]) < float(row["open"])
    )


def _m5_trigger(row: pd.Series, *, direction: str, mode: str) -> bool:
    atr = float(row["atr14"]) if pd.notna(row["atr14"]) else np.nan
    if direction == "LONG":
        basic = (
            pd.notna(row["prev3_high"])
            and float(row["close"]) > float(row["prev3_high"])
            and float(row["close"]) > float(row["open"])
        )
        displacement = (
            basic
            and np.isfinite(atr)
            and atr > 0
            and float(row["body"]) >= 0.60 * atr
            and float(row["close_loc"]) >= 0.70
        )
    else:
        basic = (
            pd.notna(row["prev3_low"])
            and float(row["close"]) < float(row["prev3_low"])
            and float(row["close"]) < float(row["open"])
        )
        displacement = (
            basic
            and np.isfinite(atr)
            and atr > 0
            and float(row["body"]) >= 0.60 * atr
            and float(row["close_loc"]) <= 0.30
        )
    return bool(displacement if mode == "DISPLACEMENT_BREAK" else basic)


def _resolve_trade(
    m1: pd.DataFrame,
    *,
    entry_at: pd.Timestamp,
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    ts = m1["timestamp"].to_numpy(dtype="datetime64[ns]")
    entry_np = np.datetime64(entry_at.to_datetime64())
    start = int(np.searchsorted(ts, entry_np, side="left"))
    if start >= len(m1):
        return {"status": "NO_M1_ENTRY_BAR"}

    deadline = entry_at + pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    end = int(
        np.searchsorted(
            ts,
            np.datetime64(deadline.to_datetime64()),
            side="right",
        )
    )
    end = min(end, len(m1))
    if end <= start:
        return {"status": "NO_M1_HORIZON"}

    for idx in range(start, end):
        row = m1.iloc[idx]
        timestamp = pd.Timestamp(row["timestamp"])
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
                "exit_at": timestamp.isoformat(),
                "exit_price": stop,
                "gross_points": gross,
            }
        if idx > start and tp_hit:
            gross = target - entry if direction == "LONG" else entry - target
            return {
                "status": "TP",
                "exit_at": timestamp.isoformat(),
                "exit_price": target,
                "gross_points": gross,
            }

    last = m1.iloc[end - 1]
    exit_price = float(last["close"])
    gross = exit_price - entry if direction == "LONG" else entry - exit_price
    return {
        "status": "TIME_EXIT_16H",
        "exit_at": pd.Timestamp(last["timestamp"]).isoformat(),
        "exit_price": exit_price,
        "gross_points": gross,
    }


def generate_year(m1: pd.DataFrame, *, year: int) -> dict[str, Any]:
    m5, m15, h1, h4 = _prepare_htf(m1)
    m15 = _attach_completed_context(m15, h1, h4)

    m5_close_ns = m5["close_at"].to_numpy(dtype="datetime64[ns]")
    trades: list[dict[str, Any]] = []
    diagnostics: dict[str, dict[str, int]] = {
        variant["variant_id"]: {
            "m15_setups": 0,
            "m5_triggered": 0,
            "valid_geometry": 0,
            "year_fills": 0,
        }
        for variant in VARIANTS
    }

    for variant in VARIANTS:
        variant_id = str(variant["variant_id"])
        pullback_ema = int(variant["pullback_ema"])
        mode = str(variant["trigger_mode"])
        last_fill: dict[str, pd.Timestamp | None] = {"LONG": None, "SHORT": None}

        for _, row in m15.iterrows():
            if (
                pd.isna(row.get("h4_direction"))
                or pd.isna(row.get("h1_permission"))
                or pd.isna(row.get("atr14"))
            ):
                continue

            direction: str | None = None
            if _setup_pass(row, direction="LONG", pullback_ema=pullback_ema):
                direction = "LONG"
            elif _setup_pass(row, direction="SHORT", pullback_ema=pullback_ema):
                direction = "SHORT"
            if direction is None:
                continue

            diagnostics[variant_id]["m15_setups"] += 1
            setup_close = pd.Timestamp(row["close_at"])
            start = int(
                np.searchsorted(
                    m5_close_ns,
                    np.datetime64(setup_close.to_datetime64()),
                    side="right",
                )
            )
            stop_search = min(len(m5), start + M5_TRIGGER_WINDOW_BARS)
            trigger_index: int | None = None
            for idx in range(start, stop_search):
                if _m5_trigger(m5.iloc[idx], direction=direction, mode=mode):
                    trigger_index = idx
                    break
            if trigger_index is None or trigger_index + 1 >= len(m5):
                continue

            diagnostics[variant_id]["m5_triggered"] += 1
            entry_row = m5.iloc[trigger_index + 1]
            fill_at = pd.Timestamp(entry_row["timestamp"])
            if fill_at.year != year:
                continue

            previous_fill = last_fill[direction]
            if (
                previous_fill is not None
                and fill_at < previous_fill + pd.Timedelta(minutes=COOLDOWN_MINUTES)
            ):
                continue

            entry = float(entry_row["open"])
            atr = float(row["atr14"])
            if direction == "LONG":
                stop = float(row["structural_low"]) - STOP_BUFFER_ATR * atr
                risk = entry - stop
                target = entry + TARGET_R * risk
            else:
                stop = float(row["structural_high"]) + STOP_BUFFER_ATR * atr
                risk = stop - entry
                target = entry - TARGET_R * risk

            if (
                not np.isfinite(risk)
                or risk <= 0
                or stop <= 0
                or target <= 0
            ):
                continue

            diagnostics[variant_id]["valid_geometry"] += 1
            outcome = _resolve_trade(
                m1,
                entry_at=fill_at,
                entry=entry,
                stop=stop,
                target=target,
                direction=direction,
            )
            if outcome.get("gross_points") is None:
                continue

            diagnostics[variant_id]["year_fills"] += 1
            last_fill[direction] = fill_at
            trades.append(
                {
                    "year": year,
                    "variant_id": variant_id,
                    "family": "H4_H1_M15_M5_CONTINUATION",
                    "direction": direction,
                    "pullback_ema": pullback_ema,
                    "trigger_mode": mode,
                    "setup_at": setup_close.isoformat(),
                    "trigger_at": pd.Timestamp(m5.iloc[trigger_index]["close_at"]).isoformat(),
                    "fill_at": fill_at.isoformat(),
                    "entry": entry,
                    "sl": stop,
                    "tp": target,
                    "risk_points": risk,
                    "rr": TARGET_R,
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
            "H1": "EMA20_50_PLUS_RECENT_12_BAR_BOS_WITHIN_8_H1_BARS",
            "M15": "EMA20_OR_EMA50_PULLBACK_RECLAIM_WITH_DIRECTIONAL_CLOSE",
            "M5": "3_BAR_BREAK_OR_DISPLACEMENT_BREAK_THEN_NEXT_M5_OPEN",
            "stop": "M15_4_BAR_STRUCTURAL_EXTREME_PLUS_0_10_ATR",
            "target": "FIXED_2R",
            "max_hold": "16H",
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
        "XAU_V233_PRICE_CSV",
        f"/tmp/histdata/xau-v233-{year}.csv",
    )
    output = Path(
        os.getenv(
            "XAU_V233_OUTPUT",
            f"artifacts/xau-h4-h1-m15-m5-continuation-v233-{year}.json",
        )
    )
    result = generate_year(_load_m1(price_path), year=year)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        "XAU_V233_YEAR "
        f"year={year} trades={len(result['trades'])} "
        f"variants={len(VARIANTS)} authority=SHADOW_ONLY"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

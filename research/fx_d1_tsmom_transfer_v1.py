from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

CONTRACT = "FX_D1_TSMOM_60_200_TRANSFER_V1"
EXECUTION_INFLUENCE = False
SEED = 20260913
DATA_START = datetime(2012, 1, 1)
DATA_END = datetime(2026, 9, 1)
VALIDATION_START = pd.Timestamp("2021-01-01", tz="UTC")
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
NY = ZoneInfo("America/New_York")
STOP_ATR = 2.0
TARGET_ATR = 4.0
MAX_HOLD_D1 = 30
PIP = 0.0001
COSTS = {
    "base_1p2_pip": 1.2 * PIP,
    "stress_1p5_pip": 1.5 * PIP,
    "stress_2p0_pip": 2.0 * PIP,
}
SYMBOLS = {
    "USDCAD": instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
    "NZDUSD": instruments.INSTRUMENT_FX_MAJORS_NZD_USD,
    "USDCHF": instruments.INSTRUMENT_FX_MAJORS_USD_CHF,
}


def _normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"{symbol}: empty Dukascopy H1 history")
    frame = raw.copy().reset_index()
    columns = {str(column).lower(): column for column in frame.columns}
    time_column = columns.get("timestamp") or columns.get("time") or frame.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close"):
        source = columns.get(column)
        if source is None:
            raise RuntimeError(f"{symbol}: missing {column}; columns={list(frame.columns)}")
        out[column] = pd.to_numeric(frame[source], errors="coerce")
    out = (
        out.dropna()
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )
    if len(out) < 50_000:
        raise RuntimeError(f"{symbol}: insufficient H1 history {len(out)}")
    return out


def fetch_h1(symbol: str) -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=SYMBOLS[symbol],
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    return _normalize(raw, symbol)


def _session_start_utc(session_date) -> pd.Timestamp:
    local_start = datetime.combine(session_date, time(17, 0), tzinfo=NY)
    return pd.Timestamp(local_start).tz_convert("UTC")


def aggregate_ny17(h1: pd.DataFrame) -> pd.DataFrame:
    frame = h1.copy().sort_values("time").reset_index(drop=True)
    local = frame["time"].dt.tz_convert(NY)
    frame["session_date"] = (local - pd.Timedelta(hours=17)).dt.date
    rows: list[dict[str, object]] = []
    for session_date, day in frame.groupby("session_date", sort=True):
        if day.empty:
            continue
        rows.append(
            {
                "time": _session_start_utc(session_date),
                "open": float(day["open"].iloc[0]),
                "high": float(day["high"].max()),
                "low": float(day["low"].min()),
                "close": float(day["close"].iloc[-1]),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("NY17 aggregation produced no rows")
    return out.sort_values("time").reset_index(drop=True)


def add_indicators(d1: pd.DataFrame) -> pd.DataFrame:
    frame = d1.copy().reset_index(drop=True)
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr14"] = true_range.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean()
    frame["ema200"] = frame["close"].ewm(
        span=200, adjust=False, min_periods=200
    ).mean()
    frame["ret60"] = frame["close"] / frame["close"].shift(60) - 1.0
    return frame


def simulate(symbol: str, d1: pd.DataFrame) -> pd.DataFrame:
    frame = add_indicators(d1)
    long_signal = (frame["close"] > frame["ema200"]) & (frame["ret60"] > 0)
    short_signal = (frame["close"] < frame["ema200"]) & (frame["ret60"] < 0)
    direction = np.where(long_signal, 1, np.where(short_signal, -1, 0))

    rows: list[dict[str, object]] = []
    index = 0
    while index < len(frame) - 1:
        side = int(direction[index])
        if side == 0:
            index += 1
            continue
        atr = float(frame.loc[index, "atr14"])
        if not np.isfinite(atr) or atr <= 0:
            index += 1
            continue

        entry_index = index + 1
        entry = float(frame.loc[entry_index, "open"])
        risk = STOP_ATR * atr
        stop = entry - side * risk
        target = entry + side * TARGET_ATR * atr
        final_index = min(len(frame) - 1, entry_index + MAX_HOLD_D1 - 1)
        exit_index = final_index
        gross_r: float | None = None
        exit_reason = "TIME"

        for probe in range(entry_index, final_index + 1):
            high = float(frame.loc[probe, "high"])
            low = float(frame.loc[probe, "low"])
            if side > 0:
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                stop_hit = high >= stop
                target_hit = low <= target
            if stop_hit:
                gross_r = -1.0
                exit_index = probe
                exit_reason = "STOP"
                break
            if target_hit:
                gross_r = TARGET_ATR / STOP_ATR
                exit_index = probe
                exit_reason = "TARGET"
                break

        if gross_r is None:
            exit_price = float(frame.loc[exit_index, "close"])
            gross_r = side * (exit_price - entry) / risk

        rows.append(
            {
                "symbol": symbol,
                "signal_time": frame.loc[index, "time"],
                "entry_time": frame.loc[entry_index, "time"],
                "exit_time": frame.loc[exit_index, "time"],
                "direction": side,
                "entry": entry,
                "risk_price": risk,
                "gross_r": gross_r,
                "exit_reason": exit_reason,
            }
        )
        index = exit_index + 1

    trades = pd.DataFrame(rows)
    if trades.empty:
        raise RuntimeError(f"{symbol}: no D1 TSMOM trades")
    return trades.sort_values("entry_time").reset_index(drop=True)


def _profit_factor(values: np.ndarray) -> float:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses <= 0:
        return 999.0 if gains > 0 else 0.0
    return gains / losses


def metrics(trades: pd.DataFrame, *, cost_abs: float) -> dict[str, object]:
    if trades.empty:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "max_dd_r": 0.0,
            "bootstrap_positive_fraction_500": 0.0,
        }
    values = (
        trades["gross_r"].to_numpy(float)
        - float(cost_abs) / trades["risk_price"].to_numpy(float)
    )
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.r_[0.0, equity])
    drawdown = peak[1:] - equity
    rng = np.random.default_rng(SEED)
    positive = 0
    for _ in range(500):
        sample = rng.choice(values, size=len(values), replace=True)
        if float(sample.mean()) > 0:
            positive += 1
    return {
        "trades": int(len(values)),
        "net_r": float(values.sum()),
        "expectancy_r": float(values.mean()),
        "profit_factor": float(_profit_factor(values)),
        "win_rate": float((values > 0).mean()),
        "max_dd_r": float(drawdown.max() if len(drawdown) else 0.0),
        "bootstrap_positive_fraction_500": positive / 500.0,
    }


def split(trades: pd.DataFrame, label: str) -> pd.DataFrame:
    if label == "development":
        return trades[trades["entry_time"] < VALIDATION_START]
    if label == "validation":
        return trades[
            (trades["entry_time"] >= VALIDATION_START)
            & (trades["entry_time"] < OOS_START)
        ]
    if label == "oos":
        return trades[trades["entry_time"] >= OOS_START]
    raise ValueError(label)


def formal_pass(validation: dict[str, object], oos: dict[str, object]) -> bool:
    return bool(
        int(validation["trades"]) >= 30
        and float(validation["win_rate"]) >= 0.50
        and float(validation["profit_factor"]) >= 1.10
        and float(validation["expectancy_r"]) >= 0.05
        and float(validation["max_dd_r"]) <= 12.0
        and float(validation["bootstrap_positive_fraction_500"]) >= 0.70
        and int(oos["trades"]) >= 30
        and float(oos["win_rate"]) >= 0.50
        and float(oos["profit_factor"]) >= 1.10
        and float(oos["expectancy_r"]) >= 0.05
        and float(oos["max_dd_r"]) <= 12.0
        and float(oos["bootstrap_positive_fraction_500"]) >= 0.70
    )


def main() -> None:
    rows: list[dict[str, object]] = []
    coverage: dict[str, object] = {}
    for symbol in SYMBOLS:
        print(f"FETCH {symbol} H1 2012-2026")
        h1 = fetch_h1(symbol)
        d1 = aggregate_ny17(h1)
        trades = simulate(symbol, d1)
        coverage[symbol] = {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "d1_rows": int(len(d1)),
            "trades": int(len(trades)),
        }
        by_cost: dict[str, object] = {}
        for cost_label, cost_abs in COSTS.items():
            by_cost[cost_label] = {
                partition: metrics(split(trades, partition), cost_abs=cost_abs)
                for partition in ("development", "validation", "oos")
            }
        validation = by_cost["stress_1p5_pip"]["validation"]
        oos = by_cost["stress_1p5_pip"]["oos"]
        rows.append(
            {
                "symbol": symbol,
                "costs": by_cost,
                "historical_pass": formal_pass(validation, oos),
            }
        )

    ranked = sorted(
        rows,
        key=lambda row: (
            float(row["costs"]["stress_1p5_pip"]["validation"]["expectancy_r"]),
            float(row["costs"]["stress_1p5_pip"]["validation"]["profit_factor"]),
        ),
        reverse=True,
    )
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "source": "DUKASCOPY_PUBLIC_BID_H1",
        "symbols": list(SYMBOLS),
        "transferred_from": "XAUUSD_D1_TSMOM_60_200_WITHOUT_PARAMETER_CHANGE",
        "boundary": "17:00 America/New_York DST-aware",
        "strategy": {
            "trend": "close vs EMA200",
            "momentum": "60D return same sign",
            "entry": "next D1 open",
            "stop_atr": STOP_ATR,
            "target_atr": TARGET_ATR,
            "reward_r": TARGET_ATR / STOP_ATR,
            "max_hold_d1": MAX_HOLD_D1,
            "same_bar_policy": "STOP_FIRST",
            "non_overlap": True,
        },
        "partitions": {
            "development": "2012-01..2020-12",
            "validation": "2021-01..2024-12",
            "oos_final_audit": "2025-01..2026-08",
            "oos_used_for_selection": False,
        },
        "cost_contract": {
            "base_round_trip_pips": 1.2,
            "formal_stress_round_trip_pips": 1.5,
            "diagnostic_stress_round_trip_pips": 2.0,
        },
        "formal_gate_from_repo_validation_contract": {
            "validation_and_oos_trades_min": 30,
            "win_rate_min": 0.50,
            "profit_factor_min": 1.10,
            "expectancy_r_min": 0.05,
            "max_drawdown_r": 12.0,
            "bootstrap_positive_fraction_500_min": 0.70,
            "purpose": "research/shadow eligibility only; no direct execution authority",
        },
        "coverage": coverage,
        "historical_pass": [
            row["symbol"] for row in ranked if row["historical_pass"]
        ],
        "validation_ranking": [row["symbol"] for row in ranked],
        "rows": ranked,
    }

    output = Path("research_output_fx_d1_tsmom_transfer_v1")
    output.mkdir(exist_ok=True)
    (output / "fx_d1_tsmom_transfer_v1.json").write_text(
        json.dumps(result, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, default=str, allow_nan=False))


if __name__ == "__main__":
    main()

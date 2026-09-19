from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

CONTRACT = "ASIA_LONDON_BREAKOUT_V1"
EXECUTION_INFLUENCE = False
DATA_START = datetime(2022, 1, 1)
DATA_END = datetime(2026, 9, 1)
DEV_END = pd.Timestamp("2023-12-31 23:59:59")
VALIDATION_END = pd.Timestamp("2024-12-31 23:59:59")
BASE_COST_PIPS = 1.2
STRESS_COSTS = (1.2, 1.5, 2.0)
SAME_BAR_POLICY = "STOP_FIRST"
LONDON_TZ = ZoneInfo("Europe/London")

# Preregistered before inspecting this strategy version's outcomes.
# Session clock is London-local and therefore DST-aware.
ASIA_RANGE_START_MINUTE = 0        # 00:00 London local
ASIA_RANGE_END_MINUTE = 6 * 60 + 55  # 06:55 inclusive
BREAKOUT_START_MINUTE = 7 * 60     # 07:00 London local
BREAKOUT_END_MINUTE = 10 * 60 + 55   # 10:55 inclusive
BREAK_BUFFER_ATR = 0.05
STOP_ATR = 1.0
TARGET_R = 1.5
MAX_HOLD_BARS = 36                 # 3 hours on M5
MIN_ASIA_BARS = 72                 # fail closed on incomplete session
ATR_PERIOD = 14
SEED = 20260912

PAIR_INSTRUMENTS = {
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "USDCHF": instruments.INSTRUMENT_FX_MAJORS_USD_CHF,
    "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
    "USDCAD": instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
}


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def fetch_pair(pair: str) -> pd.DataFrame:
    df = dukascopy_python.fetch(
        instrument=PAIR_INSTRUMENTS[pair],
        interval=dukascopy_python.INTERVAL_MIN_5,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    if df is None or df.empty:
        raise RuntimeError(f"{pair}: no M5 data")
    x = df.copy().reset_index()
    cols = {str(c).lower(): c for c in x.columns}
    time_col = cols.get("timestamp") or cols.get("time") or x.columns[0]
    out = pd.DataFrame()
    out["time_utc"] = pd.to_datetime(x[time_col], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        src = cols.get(c)
        if src is None:
            raise RuntimeError(f"{pair}: missing {c}; columns={list(x.columns)}")
        out[c] = pd.to_numeric(x[src], errors="coerce")
    out = out.dropna().drop_duplicates("time_utc").sort_values("time_utc").reset_index(drop=True)
    if len(out) < 150_000:
        raise RuntimeError(f"{pair}: insufficient M5 coverage: {len(out)}")
    if out["time_utc"].max() < pd.Timestamp("2026-08-25", tz="UTC"):
        raise RuntimeError(f"{pair}: stale M5 data through {out['time_utc'].max()}")
    return out


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            (x["high"] - x["low"]).abs(),
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False, min_periods=ATR_PERIOD).mean()
    local = x["time_utc"].dt.tz_convert(LONDON_TZ)
    x["local_date"] = local.dt.date
    x["local_minute"] = local.dt.hour * 60 + local.dt.minute
    return x


def simulate_day(pair: str, day: pd.DataFrame) -> dict | None:
    asia = day[
        (day["local_minute"] >= ASIA_RANGE_START_MINUTE)
        & (day["local_minute"] <= ASIA_RANGE_END_MINUTE)
    ]
    window = day[
        (day["local_minute"] >= BREAKOUT_START_MINUTE)
        & (day["local_minute"] <= BREAKOUT_END_MINUTE)
    ]
    if len(asia) < MIN_ASIA_BARS or window.empty:
        return None

    asia_high = float(asia["high"].max())
    asia_low = float(asia["low"].min())
    if not np.isfinite(asia_high) or not np.isfinite(asia_low) or asia_high <= asia_low:
        return None

    trigger_idx = None
    direction = 0
    signal_atr = None
    for idx, row in window.iterrows():
        atr = float(row["atr14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        if float(row["close"]) > asia_high + BREAK_BUFFER_ATR * atr:
            trigger_idx, direction, signal_atr = idx, 1, atr
            break
        if float(row["close"]) < asia_low - BREAK_BUFFER_ATR * atr:
            trigger_idx, direction, signal_atr = idx, -1, atr
            break

    if trigger_idx is None:
        return None

    entry_i = trigger_idx + 1
    if entry_i >= len(day.index):
        return None
    # day retains original integer index; locate entry by position in full dataframe externally.
    day_positions = day.index.to_list()
    try:
        trigger_pos = day_positions.index(trigger_idx)
    except ValueError:
        return None
    if trigger_pos + 1 >= len(day_positions):
        return None
    entry_idx = day_positions[trigger_pos + 1]

    entry = float(day.loc[entry_idx, "open"])
    stop_dist = STOP_ATR * float(signal_atr)
    if stop_dist <= 0:
        return None
    stop = entry - direction * stop_dist
    target = entry + direction * stop_dist * TARGET_R

    after = day.loc[entry_idx:].head(MAX_HOLD_BARS + 1)
    if after.empty:
        return None

    gross_r = None
    exit_reason = "TIME"
    exit_time = after.iloc[-1]["time_utc"]
    mfe_r = 0.0
    mae_r = 0.0

    for _, row in after.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        if direction > 0:
            mfe_r = max(mfe_r, (hi - entry) / stop_dist)
            mae_r = min(mae_r, (lo - entry) / stop_dist)
            stop_hit = lo <= stop
            target_hit = hi >= target
        else:
            mfe_r = max(mfe_r, (entry - lo) / stop_dist)
            mae_r = min(mae_r, (entry - hi) / stop_dist)
            stop_hit = hi >= stop
            target_hit = lo <= target

        if stop_hit:
            gross_r = -1.0
            exit_reason = "STOP"
            exit_time = row["time_utc"]
            break
        if target_hit:
            gross_r = TARGET_R
            exit_reason = "TARGET"
            exit_time = row["time_utc"]
            break

    if gross_r is None:
        exit_px = float(after.iloc[-1]["close"])
        gross_r = direction * (exit_px - entry) / stop_dist

    cost_r = BASE_COST_PIPS * pip_size(pair) / stop_dist
    return {
        "pair": pair,
        "strategy": CONTRACT,
        "session_date": str(day.iloc[0]["local_date"]),
        "signal_time": day.loc[trigger_idx, "time_utc"],
        "entry_time": day.loc[entry_idx, "time_utc"],
        "exit_time": exit_time,
        "direction": direction,
        "asia_high": asia_high,
        "asia_low": asia_low,
        "asia_range_pips": (asia_high - asia_low) / pip_size(pair),
        "atr_pips": float(signal_atr) / pip_size(pair),
        "gross_r": gross_r,
        "cost_r": cost_r,
        "net_r": gross_r - cost_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "exit_reason": exit_reason,
    }


def simulate_pair(pair: str, raw: pd.DataFrame) -> pd.DataFrame:
    x = add_features(raw)
    rows = []
    for _, day in x.groupby("local_date", sort=True):
        trade = simulate_day(pair, day)
        if trade is not None:
            rows.append(trade)
    return pd.DataFrame(rows)


def split_name(ts: pd.Timestamp) -> str:
    t = pd.Timestamp(ts).tz_convert("UTC").tz_localize(None)
    if t <= DEV_END:
        return "DEV_2022_2023"
    if t <= VALIDATION_END:
        return "VALIDATION_2024"
    return "OOS_2025_2026"


def metric_block(df: pd.DataFrame, cost_pips: float = BASE_COST_PIPS) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": None,
            "profit_factor": None,
            "win_rate": None,
            "max_dd_r": None,
            "avg_mfe_r": None,
            "avg_mae_r": None,
            "ci95_lo": None,
            "ci95_hi": None,
        }
    scale = cost_pips / BASE_COST_PIPS
    y = df["gross_r"].to_numpy(float) - df["cost_r"].to_numpy(float) * scale
    gp = float(y[y > 0].sum())
    gl = float(-y[y < 0].sum())
    eq = np.cumsum(y)
    peak = np.maximum.accumulate(np.r_[0.0, eq])
    dd = peak[1:] - eq
    rng = np.random.default_rng(SEED)
    means = np.empty(2000)
    for i in range(len(means)):
        means[i] = rng.choice(y, size=len(y), replace=True).mean()
    return {
        "trades": int(len(y)),
        "net_r": round(float(y.sum()), 4),
        "expectancy_r": round(float(y.mean()), 5),
        "profit_factor": None if gl <= 0 else round(gp / gl, 4),
        "win_rate": round(float((y > 0).mean()), 4),
        "max_dd_r": round(float(dd.max() if len(dd) else 0.0), 4),
        "avg_mfe_r": round(float(df["mfe_r"].mean()), 4),
        "avg_mae_r": round(float(df["mae_r"].mean()), 4),
        "ci95_lo": round(float(np.quantile(means, 0.025)), 5),
        "ci95_hi": round(float(np.quantile(means, 0.975)), 5),
    }


def main() -> None:
    all_trades = []
    coverage = {}
    for pair in PAIR_INSTRUMENTS:
        raw = fetch_pair(pair)
        coverage[pair] = {
            "rows": int(len(raw)),
            "start": str(raw["time_utc"].min()),
            "end": str(raw["time_utc"].max()),
        }
        trades = simulate_pair(pair, raw)
        all_trades.append(trades)

    trades = pd.concat(all_trades, ignore_index=True)
    trades["split"] = trades["entry_time"].map(split_name)
    trades = trades.sort_values(["entry_time", "pair"]).reset_index(drop=True)

    pair_split = {}
    for pair in PAIR_INSTRUMENTS:
        pair_split[pair] = {}
        p = trades[trades["pair"] == pair]
        for split in ("DEV_2022_2023", "VALIDATION_2024", "OOS_2025_2026"):
            pair_split[pair][split] = metric_block(p[p["split"] == split])
        pair_split[pair]["ALL"] = metric_block(p)
        pair_split[pair]["OOS_COST_STRESS"] = {
            str(cost): metric_block(p[p["split"] == "OOS_2025_2026"], cost)
            for cost in STRESS_COSTS
        }

    aggregate = {
        split: metric_block(trades[trades["split"] == split])
        for split in ("DEV_2022_2023", "VALIDATION_2024", "OOS_2025_2026")
    }

    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "data_source": "Dukascopy Bank public historical feed via dukascopy-python",
        "offer_side": "BID",
        "timeframe": "M5",
        "data_start": str(DATA_START.date()),
        "data_end_exclusive": str(DATA_END.date()),
        "splits": {
            "development": "2022-01-01..2023-12-31",
            "validation": "2024-01-01..2024-12-31",
            "oos": "2025-01-01..2026-08-31",
        },
        "same_bar_policy": SAME_BAR_POLICY,
        "base_roundtrip_cost_pips": BASE_COST_PIPS,
        "session_clock": "Europe/London DST-aware",
        "rules": {
            "asia_range": "00:00..06:55 London-local",
            "breakout_window": "07:00..10:55 London-local",
            "breakout_trigger": "first M5 close beyond Asia high/low by 0.05 ATR14",
            "entry": "next M5 bar open",
            "stop": "1.0 ATR14 from entry",
            "target": "1.5R",
            "max_hold": "36 M5 bars (3 hours)",
            "max_trades_per_session_date": 1,
            "minimum_asia_bars": MIN_ASIA_BARS,
        },
        "coverage": coverage,
        "aggregate": aggregate,
        "pair_split": pair_split,
    }

    out = Path("research_output_session_v1")
    out.mkdir(exist_ok=True)
    (out / "asia_london_breakout_v1.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    trades.to_csv(out / "asia_london_breakout_v1_trades.csv", index=False)

    rows = []
    for pair, splits in pair_split.items():
        for split in ("DEV_2022_2023", "VALIDATION_2024", "OOS_2025_2026", "ALL"):
            m = splits[split]
            rows.append({"pair": pair, "split": split, **m})
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "asia_london_breakout_v1_summary.csv", index=False)

    print("# Asia-London Breakout V1")
    print("Research-only; execution_influence=false")
    print(summary.to_string(index=False))
    print("\nOOS cost stress:")
    print(json.dumps({p: v["OOS_COST_STRESS"] for p, v in pair_split.items()}, indent=2))
    print("\nCoverage:")
    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    main()

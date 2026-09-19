from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import dukascopy_python
from dukascopy_python import instruments

CONTRACT = "FIVE_CORE_TOURNAMENT_V1"
EXECUTION_INFLUENCE = False
SEED = 20260912
DATA_END = datetime(2026, 9, 1)
SLOW_START = datetime(2018, 1, 1)
M15_START = datetime(2022, 1, 1)
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
LONDON = ZoneInfo("Europe/London")
SAME_BAR_POLICY = "STOP_FIRST"

SYMBOLS = {
    "XAUUSD": instruments.INSTRUMENT_FX_METALS_XAU_USD,
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
}

SLOW_STRATEGIES = (
    "D1_TSMOM_60_200",
    "H4_TREND_PULLBACK",
    "H4_COMPRESSION_BREAKOUT",
)
SESSION_STRATEGY = "M15_ASIA_SWEEP_REVERSAL"
ALL_STRATEGIES = (*SLOW_STRATEGIES, SESSION_STRATEGY)


def pip_size(symbol: str) -> float:
    if symbol == "XAUUSD":
        raise ValueError("XAUUSD costs are expressed in USD price units, not pips")
    return 0.01 if symbol.endswith("JPY") else 0.0001


def base_cost_abs(symbol: str) -> float:
    if symbol == "XAUUSD":
        return 0.17
    return 1.2 * pip_size(symbol)


def stress_costs(symbol: str) -> dict[str, float]:
    if symbol == "XAUUSD":
        return {"base_0.17_usd": 0.17, "stress_0.25_usd": 0.25, "stress_0.35_usd": 0.35}
    p = pip_size(symbol)
    return {"base_1.2_pip": 1.2 * p, "stress_1.5_pip": 1.5 * p, "stress_2.0_pip": 2.0 * p}


def _normalize(raw: pd.DataFrame, symbol: str, interval_name: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise RuntimeError(f"{symbol}: no {interval_name} data")
    x = raw.copy().reset_index()
    cols = {str(c).lower(): c for c in x.columns}
    time_col = cols.get("timestamp") or cols.get("time") or x.columns[0]
    out = pd.DataFrame()
    out["time"] = pd.to_datetime(x[time_col], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        src = cols.get(c)
        if src is None:
            raise RuntimeError(f"{symbol}: missing {c} in {interval_name}; columns={list(x.columns)}")
        out[c] = pd.to_numeric(x[src], errors="coerce")
    out = out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    if out.empty:
        raise RuntimeError(f"{symbol}: normalized {interval_name} data empty")
    return out


def fetch_h1(symbol: str) -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=SYMBOLS[symbol],
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=SLOW_START,
        end=DATA_END,
        max_retries=3,
    )
    out = _normalize(raw, symbol, "H1")
    if len(out) < 40_000:
        raise RuntimeError(f"{symbol}: insufficient H1 rows {len(out)}")
    return out


def fetch_m15(symbol: str) -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=SYMBOLS[symbol],
        interval=dukascopy_python.INTERVAL_MIN_15,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=M15_START,
        end=DATA_END,
        max_retries=3,
    )
    out = _normalize(raw, symbol, "M15")
    if len(out) < 80_000:
        raise RuntimeError(f"{symbol}: insufficient M15 rows {len(out)}")
    return out


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = df.set_index("time").sort_index()
    r = x.resample(rule, label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    return r.dropna().reset_index()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().reset_index(drop=True)
    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            (x["high"] - x["low"]).abs(),
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    for n in (20, 50, 200):
        x[f"ema{n}"] = x["close"].ewm(span=n, adjust=False, min_periods=n).mean()
    x["ret60"] = x["close"] / x["close"].shift(60) - 1.0
    x["prior_high20"] = x["high"].rolling(20).max().shift(1)
    x["prior_low20"] = x["low"].rolling(20).min().shift(1)
    x["atr_pct"] = x["atr14"] / x["close"]
    prior_atr_pct = x["atr_pct"].shift(1)
    x["atr_q35_prior"] = prior_atr_pct.rolling(100).quantile(0.35)
    return x


def _trade_record(
    symbol: str,
    strategy: str,
    signal_time: pd.Timestamp,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    direction: int,
    entry: float,
    stop: float,
    target: float,
    risk_price: float,
    gross_r: float,
    mfe_r: float,
    mae_r: float,
    exit_reason: str,
) -> dict:
    cost_abs = base_cost_abs(symbol)
    return {
        "symbol": symbol,
        "strategy": strategy,
        "signal_time": signal_time,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk_price": risk_price,
        "gross_r": gross_r,
        "base_cost_abs": cost_abs,
        "cost_r": cost_abs / risk_price,
        "net_r": gross_r - cost_abs / risk_price,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "exit_reason": exit_reason,
    }


def simulate_fixed_atr(
    symbol: str,
    strategy: str,
    df: pd.DataFrame,
    direction: pd.Series,
    stop_atr: float,
    target_atr: float,
    max_hold: int,
) -> pd.DataFrame:
    x = df.reset_index(drop=True)
    dirs = direction.fillna(0).astype(int).to_numpy()
    rows: list[dict] = []
    i = 0
    n = len(x)
    while i < n - 1:
        d = int(dirs[i])
        if d == 0:
            i += 1
            continue
        atr = float(x.loc[i, "atr14"])
        if not np.isfinite(atr) or atr <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(x.loc[entry_i, "open"])
        risk = stop_atr * atr
        stop = entry - d * risk
        target = entry + d * target_atr * atr
        last_i = min(n - 1, entry_i + max_hold - 1)
        gross_r = None
        exit_reason = "TIME"
        exit_i = last_i
        mfe_r = 0.0
        mae_r = 0.0
        for j in range(entry_i, last_i + 1):
            hi = float(x.loc[j, "high"])
            lo = float(x.loc[j, "low"])
            if d > 0:
                mfe_r = max(mfe_r, (hi - entry) / risk)
                mae_r = min(mae_r, (lo - entry) / risk)
                stop_hit = lo <= stop
                target_hit = hi >= target
            else:
                mfe_r = max(mfe_r, (entry - lo) / risk)
                mae_r = min(mae_r, (entry - hi) / risk)
                stop_hit = hi >= stop
                target_hit = lo <= target
            if stop_hit:
                gross_r = -1.0
                exit_reason = "STOP"
                exit_i = j
                break
            if target_hit:
                gross_r = target_atr / stop_atr
                exit_reason = "TARGET"
                exit_i = j
                break
        if gross_r is None:
            exit_px = float(x.loc[exit_i, "close"])
            gross_r = d * (exit_px - entry) / risk
        rows.append(
            _trade_record(
                symbol,
                strategy,
                x.loc[i, "time"],
                x.loc[entry_i, "time"],
                x.loc[exit_i, "time"],
                d,
                entry,
                stop,
                target,
                risk,
                gross_r,
                mfe_r,
                mae_r,
                exit_reason,
            )
        )
        i = exit_i + 1
    return pd.DataFrame(rows)


def d1_tsmom(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    d1 = add_indicators(resample_ohlc(h1, "1D"))
    long_sig = (d1["close"] > d1["ema200"]) & (d1["ret60"] > 0)
    short_sig = (d1["close"] < d1["ema200"]) & (d1["ret60"] < 0)
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=d1.index)
    return simulate_fixed_atr(symbol, "D1_TSMOM_60_200", d1, direction, 2.0, 4.0, 30)


def h4_pullback(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    h4 = add_indicators(resample_ohlc(h1, "4h"))
    long_sig = (
        (h4["ema50"] > h4["ema200"])
        & (h4["close"].shift(1) <= h4["ema20"].shift(1))
        & (h4["close"] > h4["ema20"])
    )
    short_sig = (
        (h4["ema50"] < h4["ema200"])
        & (h4["close"].shift(1) >= h4["ema20"].shift(1))
        & (h4["close"] < h4["ema20"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=h4.index)
    return simulate_fixed_atr(symbol, "H4_TREND_PULLBACK", h4, direction, 1.5, 3.0, 24)


def h4_compression_breakout(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    h4 = add_indicators(resample_ohlc(h1, "4h"))
    compressed = h4["atr_pct"].shift(1) < h4["atr_q35_prior"]
    long_sig = (
        compressed
        & (h4["ema50"] > h4["ema200"])
        & (h4["close"] > h4["prior_high20"])
    )
    short_sig = (
        compressed
        & (h4["ema50"] < h4["ema200"])
        & (h4["close"] < h4["prior_low20"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=h4.index)
    return simulate_fixed_atr(symbol, "H4_COMPRESSION_BREAKOUT", h4, direction, 1.5, 3.0, 24)


def add_m15_features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().reset_index(drop=True)
    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            (x["high"] - x["low"]).abs(),
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ], axis=1,
    ).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    local = x["time"].dt.tz_convert(LONDON)
    x["local_date"] = local.dt.date
    x["local_minute"] = local.dt.hour * 60 + local.dt.minute
    return x


def m15_asia_sweep_reversal(symbol: str, m15: pd.DataFrame) -> pd.DataFrame:
    x = add_m15_features(m15)
    rows: list[dict] = []
    for _, day in x.groupby("local_date", sort=True):
        asia = day[(day["local_minute"] >= 0) & (day["local_minute"] <= 6 * 60 + 45)]
        window = day[(day["local_minute"] >= 7 * 60) & (day["local_minute"] <= 11 * 60 + 45)]
        if len(asia) < 27 or window.empty:
            continue
        asia_high = float(asia["high"].max())
        asia_low = float(asia["low"].min())
        signal_idx = None
        direction = 0
        signal_atr = None
        signal_extreme = None
        for idx, bar in window.iterrows():
            atr = float(bar["atr14"])
            if not np.isfinite(atr) or atr <= 0:
                continue
            if float(bar["high"]) > asia_high + 0.10 * atr and float(bar["close"]) < asia_high:
                signal_idx, direction, signal_atr, signal_extreme = idx, -1, atr, float(bar["high"])
                break
            if float(bar["low"]) < asia_low - 0.10 * atr and float(bar["close"]) > asia_low:
                signal_idx, direction, signal_atr, signal_extreme = idx, 1, atr, float(bar["low"])
                break
        if signal_idx is None:
            continue
        positions = day.index.to_list()
        p = positions.index(signal_idx)
        if p + 1 >= len(positions):
            continue
        entry_idx = positions[p + 1]
        entry = float(day.loc[entry_idx, "open"])
        if direction > 0:
            stop = float(signal_extreme) - 0.25 * float(signal_atr)
            risk = entry - stop
            target = entry + 1.5 * risk
        else:
            stop = float(signal_extreme) + 0.25 * float(signal_atr)
            risk = stop - entry
            target = entry - 1.5 * risk
        if not np.isfinite(risk) or risk <= 0:
            continue
        after = day.loc[entry_idx:].head(16)
        if after.empty:
            continue
        gross_r = None
        exit_reason = "TIME"
        exit_time = after.iloc[-1]["time"]
        mfe_r = 0.0
        mae_r = 0.0
        for _, bar in after.iterrows():
            hi = float(bar["high"])
            lo = float(bar["low"])
            if direction > 0:
                mfe_r = max(mfe_r, (hi - entry) / risk)
                mae_r = min(mae_r, (lo - entry) / risk)
                stop_hit = lo <= stop
                target_hit = hi >= target
            else:
                mfe_r = max(mfe_r, (entry - lo) / risk)
                mae_r = min(mae_r, (entry - hi) / risk)
                stop_hit = hi >= stop
                target_hit = lo <= target
            if stop_hit:
                gross_r = -1.0
                exit_reason = "STOP"
                exit_time = bar["time"]
                break
            if target_hit:
                gross_r = 1.5
                exit_reason = "TARGET"
                exit_time = bar["time"]
                break
        if gross_r is None:
            exit_px = float(after.iloc[-1]["close"])
            gross_r = direction * (exit_px - entry) / risk
        rows.append(
            _trade_record(
                symbol,
                SESSION_STRATEGY,
                day.loc[signal_idx, "time"],
                day.loc[entry_idx, "time"],
                exit_time,
                direction,
                entry,
                stop,
                target,
                risk,
                gross_r,
                mfe_r,
                mae_r,
                exit_reason,
            )
        )
    return pd.DataFrame(rows)


def split_for(strategy: str, ts: pd.Timestamp) -> str:
    t = pd.Timestamp(ts).tz_convert("UTC")
    if strategy == SESSION_STRATEGY:
        if t < pd.Timestamp("2024-01-01", tz="UTC"):
            return "DEV"
        if t < pd.Timestamp("2025-01-01", tz="UTC"):
            return "VALIDATION"
        return "OOS"
    if t < pd.Timestamp("2023-01-01", tz="UTC"):
        return "DEV"
    if t < pd.Timestamp("2025-01-01", tz="UTC"):
        return "VALIDATION"
    return "OOS"


def metrics(df: pd.DataFrame, cost_abs: float | None = None) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": None,
            "profit_factor": None,
            "win_rate": None,
            "max_dd_r": None,
            "ci95_lo": None,
            "ci95_hi": None,
            "annual_net_r": {},
        }
    if cost_abs is None:
        y = df["net_r"].to_numpy(float)
    else:
        y = df["gross_r"].to_numpy(float) - float(cost_abs) / df["risk_price"].to_numpy(float)
    gp = float(y[y > 0].sum())
    gl = float(-y[y < 0].sum())
    eq = np.cumsum(y)
    peak = np.maximum.accumulate(np.r_[0.0, eq])
    dd = peak[1:] - eq
    rng = np.random.default_rng(SEED)
    means = np.empty(1000)
    for i in range(len(means)):
        means[i] = rng.choice(y, size=len(y), replace=True).mean()
    years = pd.DatetimeIndex(df["entry_time"]).year
    annual = pd.DataFrame({"year": years, "r": y}).groupby("year")["r"].sum()
    return {
        "trades": int(len(y)),
        "net_r": round(float(y.sum()), 4),
        "expectancy_r": round(float(y.mean()), 5),
        "profit_factor": None if gl <= 0 else round(gp / gl, 4),
        "win_rate": round(float((y > 0).mean()), 4),
        "max_dd_r": round(float(dd.max() if len(dd) else 0.0), 4),
        "ci95_lo": round(float(np.quantile(means, 0.025)), 5),
        "ci95_hi": round(float(np.quantile(means, 0.975)), 5),
        "annual_net_r": {str(int(k)): round(float(v), 3) for k, v in annual.items()},
    }


def candidate_status(strategy: str, m: dict) -> str:
    min_n = 25 if strategy.startswith("D1_") else 60
    if m["trades"] < min_n:
        return "INSUFFICIENT_SAMPLE"
    if m["expectancy_r"] is None or m["profit_factor"] is None:
        return "REJECT"
    if m["expectancy_r"] <= 0 or m["profit_factor"] <= 1.0:
        return "REJECT"
    return "RESEARCH_CANDIDATE"


def main() -> None:
    all_trades: list[pd.DataFrame] = []
    coverage: dict[str, dict] = {}
    for symbol in SYMBOLS:
        print(f"FETCH {symbol} H1")
        h1 = fetch_h1(symbol)
        print(f"FETCH {symbol} M15")
        m15 = fetch_m15(symbol)
        coverage[symbol] = {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
            "m15_rows": int(len(m15)),
            "m15_start": str(m15["time"].min()),
            "m15_end": str(m15["time"].max()),
        }
        print(f"SIM {symbol} D1_TSMOM_60_200")
        all_trades.append(d1_tsmom(symbol, h1))
        print(f"SIM {symbol} H4_TREND_PULLBACK")
        all_trades.append(h4_pullback(symbol, h1))
        print(f"SIM {symbol} H4_COMPRESSION_BREAKOUT")
        all_trades.append(h4_compression_breakout(symbol, h1))
        print(f"SIM {symbol} M15_ASIA_SWEEP_REVERSAL")
        all_trades.append(m15_asia_sweep_reversal(symbol, m15))

    nonempty = [d for d in all_trades if d is not None and not d.empty]
    trades = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    if trades.empty:
        raise RuntimeError("no trades generated")
    trades["split"] = [split_for(s, t) for s, t in zip(trades["strategy"], trades["entry_time"])]
    trades = trades.sort_values(["entry_time", "symbol", "strategy"]).reset_index(drop=True)

    scorecard: dict[str, dict] = {}
    rows: list[dict] = []
    stress: dict[str, dict] = {}
    for symbol in SYMBOLS:
        scorecard[symbol] = {}
        stress[symbol] = {}
        for strategy in ALL_STRATEGIES:
            d = trades[(trades["symbol"] == symbol) & (trades["strategy"] == strategy)]
            scorecard[symbol][strategy] = {}
            for split in ("DEV", "VALIDATION", "OOS", "ALL"):
                subset = d if split == "ALL" else d[d["split"] == split]
                m = metrics(subset)
                if split == "OOS":
                    m["status"] = candidate_status(strategy, m)
                scorecard[symbol][strategy][split] = m
                rows.append({"symbol": symbol, "strategy": strategy, "split": split, **{k: v for k, v in m.items() if k != "annual_net_r"}})
            oos = d[d["split"] == "OOS"]
            stress[symbol][strategy] = {
                label: metrics(oos, cost_abs=cost)
                for label, cost in stress_costs(symbol).items()
            }

    oos_rank = []
    for symbol in SYMBOLS:
        for strategy in ALL_STRATEGIES:
            m = scorecard[symbol][strategy]["OOS"]
            oos_rank.append({
                "symbol": symbol,
                "strategy": strategy,
                "trades": m["trades"],
                "expectancy_r": m["expectancy_r"],
                "profit_factor": m["profit_factor"],
                "net_r": m["net_r"],
                "max_dd_r": m["max_dd_r"],
                "ci95_lo": m["ci95_lo"],
                "ci95_hi": m["ci95_hi"],
                "status": m["status"],
                "annual_net_r": m["annual_net_r"],
            })
    oos_rank = sorted(oos_rank, key=lambda r: (-999 if r["expectancy_r"] is None else r["expectancy_r"]), reverse=True)

    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "data_source": "Dukascopy Bank public BID historical feed via dukascopy-python",
        "same_bar_policy": SAME_BAR_POLICY,
        "universe": list(SYMBOLS),
        "cost_contract": {
            "fx_base_roundtrip_pips": 1.2,
            "fx_stress_roundtrip_pips": [1.5, 2.0],
            "xauusd_base_roundtrip_usd": 0.17,
            "xauusd_stress_roundtrip_usd": [0.25, 0.35],
        },
        "coverage": coverage,
        "scorecard": scorecard,
        "oos_cost_stress": stress,
        "oos_ranking": oos_rank,
    }

    out = Path("research_output_five_core_v1")
    out.mkdir(exist_ok=True)
    (out / "five_core_tournament_v1.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    trades.to_csv(out / "five_core_tournament_v1_trades.csv", index=False)
    pd.DataFrame(rows).to_csv(out / "five_core_tournament_v1_summary.csv", index=False)
    pd.DataFrame(oos_rank).to_csv(out / "five_core_tournament_v1_oos_ranking.csv", index=False)

    print("\n# FIVE CORE TOURNAMENT V1 — OOS RANKING")
    print(pd.DataFrame(oos_rank).drop(columns=["annual_net_r"]).to_string(index=False))
    print("\n# COVERAGE")
    print(json.dumps(coverage, indent=2))
    print("\nResearch only: execution_influence=false")


if __name__ == "__main__":
    main()

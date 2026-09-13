from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

CONTRACT = "FOUR_PAIR_STRATEGY_SEARCH_V1"
EXECUTION_INFLUENCE = False
SEED = 20260913
DATA_START = datetime(2012, 1, 1)
DATA_END = datetime(2026, 9, 1)
SAME_BAR_POLICY = "STOP_FIRST"

SYMBOLS = {
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
}

ERAS = (
    ("2012_2015", pd.Timestamp("2012-01-01", tz="UTC"), pd.Timestamp("2016-01-01", tz="UTC")),
    ("2016_2019", pd.Timestamp("2016-01-01", tz="UTC"), pd.Timestamp("2020-01-01", tz="UTC")),
    ("2020_2023", pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="UTC")),
    ("2024_2026", pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-09-01", tz="UTC")),
)

# Small, predeclared candidate sets. The purpose is family discovery and robustness,
# not parameter optimization. No candidate may obtain execution authority from this run.
PAIR_CANDIDATES = {
    "USDJPY": (
        "D1_TSMOM_60_200",
        "D1_DONCHIAN55_200",
        "H4_COMPRESSION20_TREND",
        "H4_COMPRESSION20_CAUSAL_GATE20",
        "H4_DONCHIAN40_ADX20",
        "H4_PULLBACK_ADX20",
    ),
    "GBPUSD": (
        "H1_ASIA_LONDON_BREAKOUT_TREND",
        "H1_ASIA_LONDON_BREAKOUT_RAW",
        "H4_DONCHIAN40_ADX20",
        "H4_RSI2_TREND_PULLBACK",
        "D1_DONCHIAN55_200",
        "D1_TSMOM_60_200",
    ),
    "EURUSD": (
        "H4_MEAN_REVERT_Z2_ADX20",
        "H4_MEAN_REVERT_Z175_ADX18",
        "H4_RSI2_TREND_PULLBACK",
        "H4_COMPRESSION20_TREND",
        "D1_TSMOM_60_200",
        "H1_ASIA_LONDON_BREAKOUT_TREND",
    ),
    "AUDUSD": (
        "D1_TSMOM_60_200",
        "D1_TSMOM_120_200",
        "D1_DONCHIAN55_200",
        "H4_DONCHIAN40_ADX20",
        "H4_PULLBACK_ADX20",
        "H4_MEAN_REVERT_Z2_ADX20",
    ),
}


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def cost_abs(symbol: str, pips: float) -> float:
    return pips * pip_size(symbol)


def fetch_h1(symbol: str) -> pd.DataFrame:
    raw = dukascopy_python.fetch(
        instrument=SYMBOLS[symbol],
        interval=dukascopy_python.INTERVAL_HOUR_1,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=DATA_START,
        end=DATA_END,
        max_retries=3,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"{symbol}: public H1 data unavailable")
    x = raw.copy().reset_index()
    lower = {str(c).lower(): c for c in x.columns}
    tcol = lower.get("timestamp") or lower.get("time") or x.columns[0]
    out = pd.DataFrame({"time": pd.to_datetime(x[tcol], utc=True, errors="coerce")})
    for name in ("open", "high", "low", "close"):
        src = lower.get(name)
        if src is None:
            raise RuntimeError(f"{symbol}: missing {name}; columns={list(x.columns)}")
        out[name] = pd.to_numeric(x[src], errors="coerce")
    out = out.dropna().drop_duplicates("time").sort_values("time").reset_index(drop=True)
    if len(out) < 70_000:
        raise RuntimeError(f"{symbol}: insufficient H1 rows={len(out)}")
    return out


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = df.set_index("time").sort_index()
    r = x.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    return r.dropna().reset_index()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().reset_index(drop=True)
    pc = x["close"].shift(1)
    tr = pd.concat([(x["high"] - x["low"]).abs(), (x["high"] - pc).abs(), (x["low"] - pc).abs()], axis=1).max(axis=1)
    x["atr14"] = _wilder(tr, 14)
    for n in (20, 50, 200):
        x[f"ema{n}"] = x["close"].ewm(span=n, adjust=False, min_periods=n).mean()
    x["ret60"] = x["close"] / x["close"].shift(60) - 1.0
    x["ret120"] = x["close"] / x["close"].shift(120) - 1.0
    for n in (20, 40, 55):
        x[f"prior_high{n}"] = x["high"].rolling(n).max().shift(1)
        x[f"prior_low{n}"] = x["low"].rolling(n).min().shift(1)
    x["atr_pct"] = x["atr14"] / x["close"]
    x["atr_q35"] = x["atr_pct"].shift(1).rolling(100).quantile(0.35)

    up = x["high"].diff()
    down = -x["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=x.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=x.index)
    plus_di = 100 * _wilder(plus_dm, 14) / x["atr14"]
    minus_di = 100 * _wilder(minus_dm, 14) / x["atr14"]
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["adx14"] = _wilder(dx, 14)

    delta = x["close"].diff()
    gain = _wilder(delta.clip(lower=0), 14)
    loss = _wilder((-delta.clip(upper=0)), 14)
    rs = gain / loss.replace(0, np.nan)
    x["rsi14"] = 100 - (100 / (1 + rs))
    gain2 = _wilder(delta.clip(lower=0), 2)
    loss2 = _wilder((-delta.clip(upper=0)), 2)
    rs2 = gain2 / loss2.replace(0, np.nan)
    x["rsi2"] = 100 - (100 / (1 + rs2))

    x["sma20"] = x["close"].rolling(20).mean()
    x["std20"] = x["close"].rolling(20).std(ddof=0)
    x["z20"] = (x["close"] - x["sma20"]) / x["std20"].replace(0, np.nan)
    return x


def trade_record(symbol: str, strategy: str, signal_time, entry_time, exit_time, d: int, entry: float, risk: float, gross_r: float, exit_reason: str) -> dict:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "signal_time": pd.Timestamp(signal_time),
        "entry_time": pd.Timestamp(entry_time),
        "exit_time": pd.Timestamp(exit_time),
        "direction": int(d),
        "entry": float(entry),
        "risk_price": float(risk),
        "gross_r": float(gross_r),
        "exit_reason": exit_reason,
    }


def simulate_fixed(symbol: str, strategy: str, df: pd.DataFrame, direction: pd.Series, stop_atr: float, target_atr: float, max_hold: int) -> pd.DataFrame:
    x = df.reset_index(drop=True)
    dirs = direction.fillna(0).astype(int).to_numpy()
    rows: list[dict] = []
    i = 0
    while i < len(x) - 1:
        d = int(dirs[i])
        if d == 0:
            i += 1
            continue
        atr = float(x.loc[i, "atr14"])
        if not math.isfinite(atr) or atr <= 0:
            i += 1
            continue
        ei = i + 1
        entry = float(x.loc[ei, "open"])
        risk = stop_atr * atr
        stop = entry - d * risk
        target = entry + d * target_atr * atr
        last = min(len(x) - 1, ei + max_hold - 1)
        gross = None
        reason = "TIME"
        xi = last
        for j in range(ei, last + 1):
            hi, lo = float(x.loc[j, "high"]), float(x.loc[j, "low"])
            stop_hit = lo <= stop if d > 0 else hi >= stop
            target_hit = hi >= target if d > 0 else lo <= target
            if stop_hit:  # conservative STOP_FIRST, including same-bar SL+TP
                gross, reason, xi = -1.0, "STOP", j
                break
            if target_hit:
                gross, reason, xi = target_atr / stop_atr, "TARGET", j
                break
        if gross is None:
            gross = d * (float(x.loc[xi, "close"]) - entry) / risk
        rows.append(trade_record(symbol, strategy, x.loc[i, "time"], x.loc[ei, "time"], x.loc[xi, "time"], d, entry, risk, gross, reason))
        i = xi + 1
    return pd.DataFrame(rows)


def d1_tsmom(symbol: str, h1: pd.DataFrame, period: int) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "1D"))
    ret = x[f"ret{period}"]
    long_sig = (x["close"] > x["ema200"]) & (ret > 0)
    short_sig = (x["close"] < x["ema200"]) & (ret < 0)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, f"D1_TSMOM_{period}_200", x, d, 2.0, 4.0, 30)


def d1_donchian55(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "1D"))
    long_sig = (x["close"] > x["ema200"]) & (x["close"] > x["prior_high55"])
    short_sig = (x["close"] < x["ema200"]) & (x["close"] < x["prior_low55"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, "D1_DONCHIAN55_200", x, d, 2.0, 4.0, 30)


def h4_compression(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "4h"))
    compressed = x["atr_pct"].shift(1) < x["atr_q35"]
    long_sig = compressed & (x["ema50"] > x["ema200"]) & (x["close"] > x["prior_high20"])
    short_sig = compressed & (x["ema50"] < x["ema200"]) & (x["close"] < x["prior_low20"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, "H4_COMPRESSION20_TREND", x, d, 1.5, 3.0, 24)


def causal_gate20(symbol: str, trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    rows = []
    p = pip_size(symbol)
    for i in range(len(trades)):
        if i < 20:
            continue
        hist = trades.iloc[i - 20:i].copy()
        hist_net = hist["gross_r"] - (2.0 * p) / hist["risk_price"]
        pos = float(hist_net[hist_net > 0].sum())
        neg = float(-hist_net[hist_net < 0].sum())
        pf = pos / neg if neg > 0 else (999.0 if pos > 0 else 0.0)
        if float(hist_net.mean()) > 0 and pf > 1.0:
            row = trades.iloc[i].copy()
            row["strategy"] = "H4_COMPRESSION20_CAUSAL_GATE20"
            rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame(columns=trades.columns)


def h4_donchian_adx(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "4h"))
    long_sig = (x["ema50"] > x["ema200"]) & (x["adx14"] >= 20) & (x["close"] > x["prior_high40"])
    short_sig = (x["ema50"] < x["ema200"]) & (x["adx14"] >= 20) & (x["close"] < x["prior_low40"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, "H4_DONCHIAN40_ADX20", x, d, 1.5, 3.0, 24)


def h4_pullback_adx(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "4h"))
    long_sig = (x["ema50"] > x["ema200"]) & (x["adx14"] >= 20) & (x["close"].shift(1) <= x["ema20"].shift(1)) & (x["close"] > x["ema20"])
    short_sig = (x["ema50"] < x["ema200"]) & (x["adx14"] >= 20) & (x["close"].shift(1) >= x["ema20"].shift(1)) & (x["close"] < x["ema20"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, "H4_PULLBACK_ADX20", x, d, 1.5, 3.0, 24)


def h4_mean_revert(symbol: str, h1: pd.DataFrame, z: float, adx_max: float, rr: float, label: str) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "4h"))
    long_sig = (x["z20"] <= -z) & (x["rsi14"] <= 30) & (x["adx14"] < adx_max)
    short_sig = (x["z20"] >= z) & (x["rsi14"] >= 70) & (x["adx14"] < adx_max)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, label, x, d, 1.5, 1.5 * rr, 12)


def h4_rsi2_trend(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = indicators(resample_ohlc(h1, "4h"))
    long_sig = (x["close"] > x["ema200"]) & (x["ema50"] > x["ema200"]) & (x["rsi2"] < 10)
    short_sig = (x["close"] < x["ema200"]) & (x["ema50"] < x["ema200"]) & (x["rsi2"] > 90)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_fixed(symbol, "H4_RSI2_TREND_PULLBACK", x, d, 1.5, 2.25, 12)


def h1_asia_london_breakout(symbol: str, h1: pd.DataFrame, trend_filter: bool) -> pd.DataFrame:
    x = indicators(h1)
    x["date"] = x["time"].dt.date
    x["hour"] = x["time"].dt.hour
    rows: list[dict] = []
    last_exit_time = pd.Timestamp("1900-01-01", tz="UTC")
    for _, day in x.groupby("date", sort=True):
        asia = day[(day["hour"] >= 0) & (day["hour"] <= 6)]
        window = day[(day["hour"] >= 7) & (day["hour"] <= 11)]
        if len(asia) < 6 or window.empty:
            continue
        rh, rl = float(asia["high"].max()), float(asia["low"].min())
        signal_idx = None
        d = 0
        atr = None
        for idx, bar in window.iterrows():
            a = float(bar["atr14"]) if pd.notna(bar["atr14"]) else float("nan")
            if not math.isfinite(a) or a <= 0:
                continue
            up = float(bar["close"]) > rh + 0.05 * a
            dn = float(bar["close"]) < rl - 0.05 * a
            if trend_filter:
                up = up and float(bar["ema50"]) > float(bar["ema200"])
                dn = dn and float(bar["ema50"]) < float(bar["ema200"])
            if up or dn:
                signal_idx, d, atr = idx, (1 if up else -1), a
                break
        if signal_idx is None:
            continue
        pos = day.index.to_list().index(signal_idx)
        if pos + 1 >= len(day.index):
            continue
        ei = day.index.to_list()[pos + 1]
        if pd.Timestamp(x.loc[ei, "time"]) <= last_exit_time:
            continue
        entry = float(x.loc[ei, "open"])
        risk = 1.25 * float(atr)
        stop, target = entry - d * risk, entry + d * 2.5 * float(atr)
        global_ei = int(ei)
        last = min(len(x) - 1, global_ei + 12 - 1)
        gross = None
        reason = "TIME"
        xi = last
        for j in range(global_ei, last + 1):
            hi, lo = float(x.loc[j, "high"]), float(x.loc[j, "low"])
            stop_hit = lo <= stop if d > 0 else hi >= stop
            target_hit = hi >= target if d > 0 else lo <= target
            if stop_hit:
                gross, reason, xi = -1.0, "STOP", j
                break
            if target_hit:
                gross, reason, xi = 2.0, "TARGET", j
                break
        if gross is None:
            gross = d * (float(x.loc[xi, "close"]) - entry) / risk
        label = "H1_ASIA_LONDON_BREAKOUT_TREND" if trend_filter else "H1_ASIA_LONDON_BREAKOUT_RAW"
        rows.append(trade_record(symbol, label, x.loc[signal_idx, "time"], x.loc[global_ei, "time"], x.loc[xi, "time"], d, entry, risk, gross, reason))
        last_exit_time = pd.Timestamp(x.loc[xi, "time"])
    return pd.DataFrame(rows)


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    comp = h4_compression(symbol, h1)
    all_frames = {
        "D1_TSMOM_60_200": d1_tsmom(symbol, h1, 60),
        "D1_TSMOM_120_200": d1_tsmom(symbol, h1, 120),
        "D1_DONCHIAN55_200": d1_donchian55(symbol, h1),
        "H4_COMPRESSION20_TREND": comp,
        "H4_COMPRESSION20_CAUSAL_GATE20": causal_gate20(symbol, comp),
        "H4_DONCHIAN40_ADX20": h4_donchian_adx(symbol, h1),
        "H4_PULLBACK_ADX20": h4_pullback_adx(symbol, h1),
        "H4_MEAN_REVERT_Z2_ADX20": h4_mean_revert(symbol, h1, 2.0, 20.0, 1.5, "H4_MEAN_REVERT_Z2_ADX20"),
        "H4_MEAN_REVERT_Z175_ADX18": h4_mean_revert(symbol, h1, 1.75, 18.0, 1.2, "H4_MEAN_REVERT_Z175_ADX18"),
        "H4_RSI2_TREND_PULLBACK": h4_rsi2_trend(symbol, h1),
        "H1_ASIA_LONDON_BREAKOUT_TREND": h1_asia_london_breakout(symbol, h1, True),
        "H1_ASIA_LONDON_BREAKOUT_RAW": h1_asia_london_breakout(symbol, h1, False),
    }
    return {k: all_frames[k] for k in PAIR_CANDIDATES[symbol]}


def repriced(trades: pd.DataFrame, symbol: str, pips: float) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    return trades["gross_r"].astype(float) - cost_abs(symbol, pips) / trades["risk_price"].astype(float)


def block_bootstrap_ci(values: np.ndarray, reps: int = 600, block: int = 5) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 10:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(SEED + n)
    means = []
    for _ in range(reps):
        sample = []
        while len(sample) < n:
            start = int(rng.integers(0, n))
            sample.extend(values[(start + j) % n] for j in range(block))
        means.append(float(np.mean(sample[:n])))
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def metrics(trades: pd.DataFrame, symbol: str, pips: float) -> dict:
    net = repriced(trades, symbol, pips)
    if net.empty:
        return {"trades": 0, "win_rate": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0, "net_r": 0.0, "max_dd_r": 0.0, "bootstrap_ci_low": None, "bootstrap_ci_high": None}
    pos = float(net[net > 0].sum())
    neg = float(-net[net < 0].sum())
    pf = pos / neg if neg > 0 else (999.0 if pos > 0 else 0.0)
    eq = net.cumsum()
    dd = eq.cummax() - eq
    lo, hi = block_bootstrap_ci(net.to_numpy())
    return {
        "trades": int(len(net)),
        "win_rate": round(float((net > 0).mean()), 6),
        "expectancy_r": round(float(net.mean()), 6),
        "profit_factor": round(float(pf), 6),
        "net_r": round(float(net.sum()), 6),
        "max_dd_r": round(float(dd.max() if len(dd) else 0.0), 6),
        "bootstrap_ci_low": None if not math.isfinite(lo) else round(lo, 6),
        "bootstrap_ci_high": None if not math.isfinite(hi) else round(hi, 6),
    }


def assess(symbol: str, strategy: str, trades: pd.DataFrame) -> dict:
    stress_full = metrics(trades, symbol, 2.0)
    era_rows = {}
    positive_eras = 0
    for name, start, end in ERAS:
        subset = trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)] if not trades.empty else trades
        m = metrics(subset, symbol, 2.0)
        era_rows[name] = m
        if m["trades"] >= 5 and m["expectancy_r"] > 0 and m["profit_factor"] > 1.0:
            positive_eras += 1
    recent = era_rows["2024_2026"]
    ci_low = stress_full["bootstrap_ci_low"]
    strong = bool(
        stress_full["trades"] >= 40
        and stress_full["expectancy_r"] >= 0.05
        and stress_full["profit_factor"] >= 1.10
        and positive_eras >= 3
        and recent["trades"] >= 8
        and recent["expectancy_r"] > 0
        and recent["profit_factor"] > 1.0
        and ci_low is not None
        and ci_low > 0
    )
    watch = bool(
        not strong
        and stress_full["trades"] >= 30
        and stress_full["expectancy_r"] > 0
        and stress_full["profit_factor"] > 1.0
        and positive_eras >= 2
        and recent["expectancy_r"] > 0
    )
    status = "STRONG_RESEARCH_PASS" if strong else ("WATCH" if watch else "REJECT")
    return {
        "symbol": symbol,
        "strategy": strategy,
        "status": status,
        "positive_eras_stress_2pip": positive_eras,
        "base_1p2": metrics(trades, symbol, 1.2),
        "stress_2p0": stress_full,
        "severe_3p0": metrics(trades, symbol, 3.0),
        "eras_stress_2p0": era_rows,
    }


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(SYMBOLS)}")
    print(f"FETCH {symbol} public Dukascopy BID H1 {DATA_START.date()}..{DATA_END.date()}")
    h1 = fetch_h1(symbol)
    print(f"COVERAGE rows={len(h1)} start={h1.time.min()} end={h1.time.max()}")
    frames = generate(symbol, h1)
    scorecard = [assess(symbol, name, trades) for name, trades in frames.items()]
    rank = {"STRONG_RESEARCH_PASS": 2, "WATCH": 1, "REJECT": 0}
    scorecard.sort(key=lambda r: (rank[r["status"]], r["stress_2p0"]["expectancy_r"], r["stress_2p0"]["profit_factor"]), reverse=True)
    champion = scorecard[0]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": symbol,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "data_start": str(DATA_START.date()),
        "data_end_exclusive": str(DATA_END.date()),
        "same_bar_policy": SAME_BAR_POLICY,
        "cost_model_pips": {"base": 1.2, "stress": 2.0, "severe": 3.0},
        "selection_rule": "small predeclared family set; STRONG requires >=40 trades, stress exp>=0.05R, PF>=1.10, >=3/4 positive eras, recent positive, moving-block bootstrap lower CI >0",
        "candidate_set": list(PAIR_CANDIDATES[symbol]),
        "coverage": {"h1_rows": int(len(h1)), "h1_start": str(h1.time.min()), "h1_end": str(h1.time.max())},
        "champion_by_rule": {"strategy": champion["strategy"], "status": champion["status"]},
        "scorecard": scorecard,
    }
    out = Path("research_output_four_pair_v1")
    out.mkdir(exist_ok=True)
    (out / f"four_pair_strategy_search_{symbol}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    for name, trades in frames.items():
        trades.to_csv(out / f"{symbol}_{name}_trades.csv", index=False)
    compact = []
    for r in scorecard:
        s = r["stress_2p0"]
        compact.append({
            "symbol": symbol, "strategy": r["strategy"], "status": r["status"],
            "trades": s["trades"], "expectancy_r": s["expectancy_r"], "pf": s["profit_factor"],
            "net_r": s["net_r"], "max_dd_r": s["max_dd_r"], "positive_eras": r["positive_eras_stress_2pip"],
            "ci_low": s["bootstrap_ci_low"], "ci_high": s["bootstrap_ci_high"],
            "recent_exp": r["eras_stress_2p0"]["2024_2026"]["expectancy_r"],
            "recent_pf": r["eras_stress_2p0"]["2024_2026"]["profit_factor"],
        })
    pd.DataFrame(compact).to_csv(out / f"four_pair_strategy_search_{symbol}_summary.csv", index=False)
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in compact:
        print("SCORE", json.dumps(row, sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base

CONTRACT = "FOUR_PAIR_STRATEGY_SEARCH_V2"
EXECUTION_INFLUENCE = False

PAIR_CANDIDATES = {
    "EURUSD": (
        "H4_MEAN_REVERT_Z2_TO_SMA20",
        "H4_MEAN_REVERT_Z175_TO_SMA20",
        "D1_TSMOM_252_CHANDELIER3",
        "D1_TSMOM_120_CHANDELIER3",
        "D1_DONCHIAN55_CHANDELIER3",
        "D1_DONCHIAN100_CHANDELIER3",
    ),
    "GBPUSD": (
        "D1_TSMOM_252_CHANDELIER3",
        "D1_TSMOM_120_CHANDELIER3",
        "D1_DONCHIAN55_CHANDELIER3",
        "D1_DONCHIAN100_CHANDELIER3",
        "H4_DONCHIAN40_CHANDELIER3",
        "H4_MEAN_REVERT_Z2_TO_SMA20",
    ),
    "USDJPY": (
        "D1_TSMOM_252_CHANDELIER3",
        "D1_TSMOM_120_CHANDELIER3",
        "D1_DONCHIAN55_CHANDELIER3",
        "D1_DONCHIAN100_CHANDELIER3",
        "H4_DONCHIAN40_CHANDELIER3",
        "H4_MEAN_REVERT_Z2_TO_SMA20",
    ),
    "AUDUSD": (
        "D1_TSMOM_252_CHANDELIER3",
        "D1_TSMOM_120_CHANDELIER3",
        "D1_DONCHIAN55_CHANDELIER3",
        "D1_DONCHIAN100_CHANDELIER3",
        "H4_DONCHIAN40_CHANDELIER3",
        "H4_MEAN_REVERT_Z2_TO_SMA20",
    ),
}


def add_long_horizon(x: pd.DataFrame) -> pd.DataFrame:
    x = base.indicators(x)
    x["ret252"] = x["close"] / x["close"].shift(252) - 1.0
    x["prior_high100"] = x["high"].rolling(100).max().shift(1)
    x["prior_low100"] = x["low"].rolling(100).min().shift(1)
    return x


def simulate_chandelier(symbol: str, strategy: str, df: pd.DataFrame, direction: pd.Series, initial_stop_atr: float, trail_atr: float, max_hold: int) -> pd.DataFrame:
    x = df.reset_index(drop=True)
    dirs = direction.fillna(0).astype(int).to_numpy()
    rows = []
    i = 0
    while i < len(x) - 1:
        d = int(dirs[i])
        if d == 0:
            i += 1
            continue
        atr0 = float(x.loc[i, "atr14"])
        if not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue
        ei = i + 1
        entry = float(x.loc[ei, "open"])
        risk = initial_stop_atr * atr0
        stop = entry - d * risk
        last = min(len(x) - 1, ei + max_hold - 1)
        highest = entry
        lowest = entry
        xi = last
        reason = "TIME"
        exit_px = float(x.loc[last, "close"])
        for j in range(ei, last + 1):
            o, hi, lo, close = (float(x.loc[j, k]) for k in ("open", "high", "low", "close"))
            if d > 0:
                if o <= stop:
                    xi, exit_px, reason = j, o, "STOP_GAP"
                    break
                if lo <= stop:
                    xi, exit_px, reason = j, stop, "STOP"
                    break
            else:
                if o >= stop:
                    xi, exit_px, reason = j, o, "STOP_GAP"
                    break
                if hi >= stop:
                    xi, exit_px, reason = j, stop, "STOP"
                    break
            highest = max(highest, hi)
            lowest = min(lowest, lo)
            atr = float(x.loc[j, "atr14"])
            if math.isfinite(atr) and atr > 0:
                candidate = highest - trail_atr * atr if d > 0 else lowest + trail_atr * atr
                stop = max(stop, candidate) if d > 0 else min(stop, candidate)
            exit_px = close
        gross = d * (exit_px - entry) / risk
        rows.append(base.trade_record(symbol, strategy, x.loc[i, "time"], x.loc[ei, "time"], x.loc[xi, "time"], d, entry, risk, gross, reason))
        i = xi + 1
    return pd.DataFrame(rows)


def d1_tsmom_trailing(symbol: str, h1: pd.DataFrame, period: int) -> pd.DataFrame:
    x = add_long_horizon(base.resample_ohlc(h1, "1D"))
    ret = x[f"ret{period}"]
    long_sig = (x["close"] > x["ema200"]) & (ret > 0)
    short_sig = (x["close"] < x["ema200"]) & (ret < 0)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_chandelier(symbol, f"D1_TSMOM_{period}_CHANDELIER3", x, d, 2.0, 3.0, 120)


def d1_donchian_trailing(symbol: str, h1: pd.DataFrame, lookback: int) -> pd.DataFrame:
    x = add_long_horizon(base.resample_ohlc(h1, "1D"))
    hi = x["prior_high55"] if lookback == 55 else x["prior_high100"]
    lo = x["prior_low55"] if lookback == 55 else x["prior_low100"]
    long_sig = (x["close"] > x["ema200"]) & (x["close"] > hi)
    short_sig = (x["close"] < x["ema200"]) & (x["close"] < lo)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_chandelier(symbol, f"D1_DONCHIAN{lookback}_CHANDELIER3", x, d, 2.0, 3.0, 120)


def h4_donchian_trailing(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = add_long_horizon(base.resample_ohlc(h1, "4h"))
    long_sig = (x["ema50"] > x["ema200"]) & (x["adx14"] >= 20) & (x["close"] > x["prior_high40"])
    short_sig = (x["ema50"] < x["ema200"]) & (x["adx14"] >= 20) & (x["close"] < x["prior_low40"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return simulate_chandelier(symbol, "H4_DONCHIAN40_CHANDELIER3", x, d, 1.5, 3.0, 60)


def h4_mean_to_sma(symbol: str, h1: pd.DataFrame, z: float, adx_max: float, label: str) -> pd.DataFrame:
    x = add_long_horizon(base.resample_ohlc(h1, "4h"))
    long_sig = (x["z20"] <= -z) & (x["rsi14"] <= 30) & (x["adx14"] < adx_max)
    short_sig = (x["z20"] >= z) & (x["rsi14"] >= 70) & (x["adx14"] < adx_max)
    dirs = np.where(long_sig, 1, np.where(short_sig, -1, 0))
    rows = []
    i = 0
    while i < len(x) - 1:
        d = int(dirs[i])
        if d == 0:
            i += 1
            continue
        atr = float(x.loc[i, "atr14"])
        target = float(x.loc[i, "sma20"])
        if not math.isfinite(atr) or atr <= 0 or not math.isfinite(target):
            i += 1
            continue
        ei = i + 1
        entry = float(x.loc[ei, "open"])
        if (d > 0 and target <= entry) or (d < 0 and target >= entry):
            i += 1
            continue
        risk = 1.5 * atr
        stop = entry - d * risk
        last = min(len(x) - 1, ei + 12 - 1)
        xi = last
        reason = "TIME"
        exit_px = float(x.loc[last, "close"])
        for j in range(ei, last + 1):
            o, hi, lo = (float(x.loc[j, k]) for k in ("open", "high", "low"))
            if d > 0:
                if o <= stop:
                    xi, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o >= target:
                    xi, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = lo <= stop, hi >= target
            else:
                if o >= stop:
                    xi, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o <= target:
                    xi, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = hi >= stop, lo <= target
            if stop_hit:
                xi, exit_px, reason = j, stop, "STOP"
                break
            if target_hit:
                xi, exit_px, reason = j, target, "TARGET"
                break
        gross = d * (exit_px - entry) / risk
        rows.append(base.trade_record(symbol, label, x.loc[i, "time"], x.loc[ei, "time"], x.loc[xi, "time"], d, entry, risk, gross, reason))
        i = xi + 1
    return pd.DataFrame(rows)


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "D1_TSMOM_252_CHANDELIER3": d1_tsmom_trailing(symbol, h1, 252),
        "D1_TSMOM_120_CHANDELIER3": d1_tsmom_trailing(symbol, h1, 120),
        "D1_DONCHIAN55_CHANDELIER3": d1_donchian_trailing(symbol, h1, 55),
        "D1_DONCHIAN100_CHANDELIER3": d1_donchian_trailing(symbol, h1, 100),
        "H4_DONCHIAN40_CHANDELIER3": h4_donchian_trailing(symbol, h1),
        "H4_MEAN_REVERT_Z2_TO_SMA20": h4_mean_to_sma(symbol, h1, 2.0, 20.0, "H4_MEAN_REVERT_Z2_TO_SMA20"),
        "H4_MEAN_REVERT_Z175_TO_SMA20": h4_mean_to_sma(symbol, h1, 1.75, 18.0, "H4_MEAN_REVERT_Z175_TO_SMA20"),
    }
    return {k: frames[k] for k in PAIR_CANDIDATES[symbol]}


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in base.SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(base.SYMBOLS)}")
    print(f"FETCH {symbol} V2 public Dukascopy BID H1")
    h1 = base.fetch_h1(symbol)
    print(f"COVERAGE rows={len(h1)} start={h1.time.min()} end={h1.time.max()}")
    frames = generate(symbol, h1)
    scorecard = [base.assess(symbol, name, trades) for name, trades in frames.items()]
    rank = {"STRONG_RESEARCH_PASS": 2, "WATCH": 1, "REJECT": 0}
    scorecard.sort(key=lambda r: (rank[r["status"]], r["stress_2p0"]["expectancy_r"], r["stress_2p0"]["profit_factor"]), reverse=True)
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": symbol,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "data_start": str(base.DATA_START.date()),
        "data_end_exclusive": str(base.DATA_END.date()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "cost_model_pips": {"base": 1.2, "stress": 2.0, "severe": 3.0},
        "research_change": "V2 changes exit family rather than tuning V1 thresholds: long-horizon trend uses ATR Chandelier; mean reversion targets signal SMA20",
        "candidate_set": list(PAIR_CANDIDATES[symbol]),
        "coverage": {"h1_rows": int(len(h1)), "h1_start": str(h1.time.min()), "h1_end": str(h1.time.max())},
        "champion_by_rule": {"strategy": scorecard[0]["strategy"], "status": scorecard[0]["status"]},
        "scorecard": scorecard,
    }
    out = Path("research_output_four_pair_v2")
    out.mkdir(exist_ok=True)
    (out / f"four_pair_strategy_search_v2_{symbol}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    for name, trades in frames.items():
        trades.to_csv(out / f"{symbol}_{name}_trades.csv", index=False)
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for r in scorecard:
        s = r["stress_2p0"]
        print("SCORE", json.dumps({
            "symbol": symbol, "strategy": r["strategy"], "status": r["status"], "trades": s["trades"],
            "expectancy_r": s["expectancy_r"], "pf": s["profit_factor"], "net_r": s["net_r"], "max_dd_r": s["max_dd_r"],
            "positive_eras": r["positive_eras_stress_2pip"], "ci_low": s["bootstrap_ci_low"], "ci_high": s["bootstrap_ci_high"],
            "recent_exp": r["eras_stress_2p0"]["2024_2026"]["expectancy_r"], "recent_pf": r["eras_stress_2p0"]["2024_2026"]["profit_factor"],
        }, sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()

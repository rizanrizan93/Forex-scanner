from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "XAUUSD"]
SOURCE = "https://raw.githubusercontent.com/komo135/forex-historical-data/main/{symbol}/{symbol}h1.csv"
REGIMES = ["TREND_HIGH_VOL", "TREND_LOW_VOL", "RANGE_HIGH_VOL", "RANGE_LOW_VOL"]
TARGET_PER_REGIME = 25
MAX_HOLD_BARS = 72
COOLDOWN_BARS = 8


def load_data(symbol: str) -> pd.DataFrame:
    url = SOURCE.format(symbol=symbol)
    df = pd.read_csv(url)
    df.columns = [str(c).strip() for c in df.columns]
    required = {"Date", "Open", "High", "Low", "Close"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"{symbol}: missing columns {sorted(missing)}")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for c in ["Open", "High", "Low", "Close", "Spread"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Spread" not in df.columns:
        df["Spread"] = 0.0
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close"]).sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    return add_features(df)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    prev_close = x["Close"].shift(1)
    tr = pd.concat(
        [
            x["High"] - x["Low"],
            (x["High"] - prev_close).abs(),
            (x["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr"] = tr.rolling(14, min_periods=14).mean()
    for p in [9, 20, 34, 50, 200]:
        x[f"ema{p}"] = x["Close"].ewm(span=p, adjust=False).mean()

    delta = x["Close"].diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    x["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    x.loc[(loss == 0) & (gain > 0), "rsi"] = 100.0
    x.loc[(gain == 0) & (loss > 0), "rsi"] = 0.0

    x["bb_mid"] = x["Close"].rolling(20, min_periods=20).mean()
    bb_sd = x["Close"].rolling(20, min_periods=20).std(ddof=0)
    x["bb_up"] = x["bb_mid"] + 2.0 * bb_sd
    x["bb_dn"] = x["bb_mid"] - 2.0 * bb_sd
    x["prior_hi20"] = x["High"].shift(1).rolling(20, min_periods=20).max()
    x["prior_lo20"] = x["Low"].shift(1).rolling(20, min_periods=20).min()
    x["prior_hi12"] = x["High"].shift(1).rolling(12, min_periods=12).max()
    x["prior_lo12"] = x["Low"].shift(1).rolling(12, min_periods=12).min()

    atr_pct = x["atr"] / x["Close"].replace(0.0, np.nan)
    # PIT threshold: only prior volatility observations enter the threshold.
    vol_threshold = atr_pct.shift(1).rolling(500, min_periods=250).quantile(0.65)
    high_vol = atr_pct > vol_threshold
    trend_strength = (x["ema50"] - x["ema200"]).abs() / x["atr"].replace(0.0, np.nan)
    slope_consistent = (x["ema50"] - x["ema50"].shift(20)).abs() / x["atr"].replace(0.0, np.nan) > 0.50
    trending = (trend_strength > 0.90) & slope_consistent
    x["regime"] = np.select(
        [trending & high_vol, trending & ~high_vol, ~trending & high_vol],
        ["TREND_HIGH_VOL", "TREND_LOW_VOL", "RANGE_HIGH_VOL"],
        default="RANGE_LOW_VOL",
    )
    return x


def apply_cooldown(records: list[dict], cooldown: int = COOLDOWN_BARS) -> list[dict]:
    records = sorted(records, key=lambda r: int(r["signal_idx"]))
    out: list[dict] = []
    last = -10**9
    for rec in records:
        idx = int(rec["signal_idx"])
        if idx - last < cooldown:
            continue
        out.append(rec)
        last = idx
    return out


def generic_records(df: pd.DataFrame, strategy: str) -> list[dict]:
    body = (df["Close"] - df["Open"]).abs()
    if strategy == "FOUR_EMA_9_20_34_50_PULLBACK":
        long = (
            (df.ema9 > df.ema20) & (df.ema20 > df.ema34) & (df.ema34 > df.ema50)
            & (df.ema9 > df.ema9.shift(5)) & (df.ema20 > df.ema20.shift(5))
            & (df.Low <= df.ema20 + 0.10 * df.atr) & (df.Close > df.ema9) & (df.Close > df.Open)
        )
        short = (
            (df.ema9 < df.ema20) & (df.ema20 < df.ema34) & (df.ema34 < df.ema50)
            & (df.ema9 < df.ema9.shift(5)) & (df.ema20 < df.ema20.shift(5))
            & (df.High >= df.ema20 - 0.10 * df.atr) & (df.Close < df.ema9) & (df.Close < df.Open)
        )
        risk_mult, rr = 1.50, 1.50
    elif strategy == "DONCHIAN_ATR_BREAKOUT":
        long = (df.Close > df.prior_hi20) & (df.Close > df.Open) & (body >= 0.50 * df.atr)
        short = (df.Close < df.prior_lo20) & (df.Close < df.Open) & (body >= 0.50 * df.atr)
        risk_mult, rr = 1.40, 2.00
    elif strategy == "RSI_BOLLINGER_MEAN_REVERSION":
        long = (df.rsi < 30.0) & (df.Low < df.bb_dn) & (df.Close > df.Open) & (df.Close > df.Low + 0.55 * (df.High - df.Low))
        short = (df.rsi > 70.0) & (df.High > df.bb_up) & (df.Close < df.Open) & (df.Close < df.Low + 0.45 * (df.High - df.Low))
        risk_mult, rr = 1.20, 1.50
    elif strategy == "SMC_LIQUIDITY_SWEEP_CHOCH_PROXY":
        long = (
            (df.Low < df.prior_lo20) & (df.Close > df.prior_lo20)
            & (df.Close > df.High.shift(1)) & (df.Close > df.Open) & (body >= 0.20 * df.atr)
        )
        short = (
            (df.High > df.prior_hi20) & (df.Close < df.prior_hi20)
            & (df.Close < df.Low.shift(1)) & (df.Close < df.Open) & (body >= 0.20 * df.atr)
        )
        risk_mult, rr = np.nan, 2.00
    elif strategy == "EMA200_TREND_PULLBACK":
        long = (
            (df.ema50 > df.ema200) & (df.ema20 > df.ema50)
            & (df.Low <= df.ema20) & (df.Close > df.ema9) & (df.Close > df.Open)
            & (df.rsi >= 50.0) & (df.rsi <= 68.0)
        )
        short = (
            (df.ema50 < df.ema200) & (df.ema20 < df.ema50)
            & (df.High >= df.ema20) & (df.Close < df.ema9) & (df.Close < df.Open)
            & (df.rsi <= 50.0) & (df.rsi >= 32.0)
        )
        risk_mult, rr = 1.30, 2.00
    else:
        raise ValueError(strategy)

    records: list[dict] = []
    for direction, mask in [("LONG", long), ("SHORT", short)]:
        idxs = np.flatnonzero(mask.fillna(False).to_numpy())
        for i in idxs:
            if i < 220 or i + 1 >= len(df) or not np.isfinite(df.at[i, "atr"]):
                continue
            rec = {
                "signal_idx": int(i),
                "direction": direction,
                "regime": str(df.at[i, "regime"]),
                "atr": float(df.at[i, "atr"]),
                "risk_mult": float(risk_mult) if np.isfinite(risk_mult) else None,
                "rr": float(rr),
            }
            if strategy == "SMC_LIQUIDITY_SWEEP_CHOCH_PROXY":
                if direction == "LONG":
                    rec["custom_stop"] = float(df.at[i, "Low"] - 0.20 * df.at[i, "atr"])
                else:
                    rec["custom_stop"] = float(df.at[i, "High"] + 0.20 * df.at[i, "atr"])
            records.append(rec)
    return apply_cooldown(records)


def impulse_retest_records(df: pd.DataFrame) -> list[dict]:
    records: list[dict] = []
    for direction in ["LONG", "SHORT"]:
        if direction == "LONG":
            close_loc = (df.Close - df.Low) / (df.High - df.Low).replace(0.0, np.nan)
            impulse_mask = (
                (df.Close > df.prior_hi12) & (df.Close > df.Open) & (close_loc >= 0.75)
                & ((df.High - df.Low) >= 1.20 * df.atr) & ((df.Close - df.Open).abs() >= 0.80 * df.atr)
            )
        else:
            close_loc = (df.High - df.Close) / (df.High - df.Low).replace(0.0, np.nan)
            impulse_mask = (
                (df.Close < df.prior_lo12) & (df.Close < df.Open) & (close_loc >= 0.75)
                & ((df.High - df.Low) >= 1.20 * df.atr) & ((df.Close - df.Open).abs() >= 0.80 * df.atr)
            )
        for j in np.flatnonzero(impulse_mask.fillna(False).to_numpy()):
            if j < 30 or j + 1 >= len(df):
                continue
            atrj = float(df.at[j, "atr"])
            if not np.isfinite(atrj) or atrj <= 0:
                continue
            level = float(df.at[j, "prior_hi12"] if direction == "LONG" else df.at[j, "prior_lo12"])
            impulse_close = float(df.at[j, "Close"])
            for k in range(j + 1, min(j + 13, len(df))):
                row = df.iloc[k]
                if direction == "LONG":
                    depth = (impulse_close - float(row.Low)) / atrj
                    accepted = float(row.Close) > level
                    invalid = float(row.Close) < level - 0.25 * atrj
                else:
                    depth = (float(row.High) - impulse_close) / atrj
                    accepted = float(row.Close) < level
                    invalid = float(row.Close) > level + 0.25 * atrj
                if invalid:
                    break
                if accepted and 0.10 <= depth <= 1.25:
                    stop = level - 0.35 * atrj if direction == "LONG" else level + 0.35 * atrj
                    records.append(
                        {
                            "signal_idx": int(k),
                            "direction": direction,
                            "regime": str(df.at[k, "regime"]),
                            "atr": atrj,
                            "risk_mult": None,
                            "rr": 1.50,
                            "custom_stop": float(stop),
                        }
                    )
                    break
    return apply_cooldown(records)


def infer_point_size(symbol: str) -> float:
    if symbol == "XAUUSD":
        return 0.01
    if symbol.endswith("JPY"):
        return 0.001
    return 0.00001


def simulate_trade(df: pd.DataFrame, symbol: str, strategy: str, rec: dict) -> dict | None:
    i = int(rec["signal_idx"])
    entry_idx = i + 1
    if entry_idx >= len(df):
        return None
    entry = float(df.at[entry_idx, "Open"])
    direction = str(rec["direction"])
    atr_value = float(rec["atr"])
    if not np.isfinite(entry) or not np.isfinite(atr_value) or atr_value <= 0:
        return None
    if rec.get("custom_stop") is not None:
        stop = float(rec["custom_stop"])
        risk = entry - stop if direction == "LONG" else stop - entry
    else:
        risk = float(rec["risk_mult"]) * atr_value
        stop = entry - risk if direction == "LONG" else entry + risk
    if not np.isfinite(risk) or risk <= 0:
        return None
    target = entry + float(rec["rr"]) * risk if direction == "LONG" else entry - float(rec["rr"]) * risk

    point = infer_point_size(symbol)
    spread_points = max(0.0, float(df.at[entry_idx, "Spread"]) if np.isfinite(df.at[entry_idx, "Spread"]) else 0.0)
    # One observed spread plus a conservative 0.02R allowance for slippage/commission.
    cost_r = (spread_points * point) / risk + 0.02
    if not np.isfinite(cost_r) or cost_r > 0.75:
        return None

    exit_idx = min(len(df) - 1, entry_idx + MAX_HOLD_BARS - 1)
    gross_r: float | None = None
    exit_reason = "TIME"
    actual_exit_idx = exit_idx
    for j in range(entry_idx, exit_idx + 1):
        lo, hi = float(df.at[j, "Low"]), float(df.at[j, "High"])
        if direction == "LONG":
            hit_stop, hit_target = lo <= stop, hi >= target
        else:
            hit_stop, hit_target = hi >= stop, lo <= target
        if hit_stop and hit_target:
            gross_r, exit_reason, actual_exit_idx = -1.0, "STOP_FIRST_AMBIGUOUS", j
            break
        if hit_stop:
            gross_r, exit_reason, actual_exit_idx = -1.0, "STOP", j
            break
        if hit_target:
            gross_r, exit_reason, actual_exit_idx = float(rec["rr"]), "TARGET", j
            break
    if gross_r is None:
        px = float(df.at[actual_exit_idx, "Close"])
        gross_r = (px - entry) / risk if direction == "LONG" else (entry - px) / risk
    net_r = float(gross_r - cost_r)
    return {
        "strategy": strategy,
        "symbol": symbol,
        "signal_at": str(df.at[i, "Date"]),
        "entry_at": str(df.at[entry_idx, "Date"]),
        "regime": str(rec["regime"]),
        "direction": direction,
        "gross_r": float(gross_r),
        "cost_r": float(cost_r),
        "net_r": net_r,
        "win": bool(net_r > 0),
        "exit_reason": exit_reason,
        "bars_held": int(actual_exit_idx - entry_idx + 1),
    }


def max_drawdown_r(values: pd.Series) -> float:
    if len(values) == 0:
        return math.nan
    equity = values.cumsum()
    peak = equity.cummax().clip(lower=0.0)
    dd = peak - equity
    return float(dd.max())


def metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0}
    wins = df.loc[df.net_r > 0, "net_r"]
    losses = df.loc[df.net_r < 0, "net_r"]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    return {
        "trades": int(len(df)),
        "win_rate": float((df.net_r > 0).mean()),
        "total_net_r": float(df.net_r.sum()),
        "avg_net_r": float(df.net_r.mean()),
        "median_net_r": float(df.net_r.median()),
        "profit_factor": float(gp / gl) if gl > 0 else None,
        "max_drawdown_r": max_drawdown_r(df.net_r.reset_index(drop=True)),
        "avg_cost_r": float(df.cost_r.mean()),
    }


def stratified_100(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    selected = []
    counts = {}
    for regime in REGIMES:
        g = df[df.regime == regime].sort_values(["entry_at", "symbol"]).reset_index(drop=True)
        counts[regime] = int(len(g))
        if len(g) < TARGET_PER_REGIME:
            continue
        # deterministic broad-in-time sample, avoiding cherry-picking random seeds.
        pos = np.linspace(0, len(g) - 1, TARGET_PER_REGIME).round().astype(int)
        selected.append(g.iloc[pos])
    if len(selected) != len(REGIMES):
        return pd.DataFrame(columns=df.columns), counts
    out = pd.concat(selected, ignore_index=True).sort_values(["entry_at", "symbol"]).reset_index(drop=True)
    return out, counts


def monte_carlo(sample: pd.DataFrame, n: int = 2000, seed: int = 1701) -> dict:
    if sample.empty:
        return {}
    arr = sample.net_r.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    totals, dds = [], []
    for _ in range(n):
        draw = rng.choice(arr, size=len(arr), replace=True)
        totals.append(float(draw.sum()))
        eq = np.cumsum(draw)
        peak = np.maximum.accumulate(np.maximum(eq, 0.0))
        dds.append(float(np.max(peak - eq)))
    return {
        "resamples": n,
        "prob_total_net_r_positive": float(np.mean(np.asarray(totals) > 0)),
        "total_net_r_p05": float(np.quantile(totals, 0.05)),
        "total_net_r_p50": float(np.quantile(totals, 0.50)),
        "max_drawdown_r_p95": float(np.quantile(dds, 0.95)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="out/strategy_regime_100")
    args = ap.parse_args()
    outdir = Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)

    strategies = [
        "FOUR_EMA_9_20_34_50_PULLBACK",
        "IMPULSE_RETEST_V2",
        "DONCHIAN_ATR_BREAKOUT",
        "RSI_BOLLINGER_MEAN_REVERSION",
        "SMC_LIQUIDITY_SWEEP_CHOCH_PROXY",
        "EMA200_TREND_PULLBACK",
    ]
    all_trades: dict[str, list[dict]] = {s: [] for s in strategies}
    coverage = {}

    for symbol in SYMBOLS:
        df = load_data(symbol)
        coverage[symbol] = {
            "rows": int(len(df)),
            "start": str(df.Date.min()),
            "end": str(df.Date.max()),
        }
        by_strategy = {
            "FOUR_EMA_9_20_34_50_PULLBACK": generic_records(df, "FOUR_EMA_9_20_34_50_PULLBACK"),
            "IMPULSE_RETEST_V2": impulse_retest_records(df),
            "DONCHIAN_ATR_BREAKOUT": generic_records(df, "DONCHIAN_ATR_BREAKOUT"),
            "RSI_BOLLINGER_MEAN_REVERSION": generic_records(df, "RSI_BOLLINGER_MEAN_REVERSION"),
            "SMC_LIQUIDITY_SWEEP_CHOCH_PROXY": generic_records(df, "SMC_LIQUIDITY_SWEEP_CHOCH_PROXY"),
            "EMA200_TREND_PULLBACK": generic_records(df, "EMA200_TREND_PULLBACK"),
        }
        for strategy, records in by_strategy.items():
            for rec in records:
                trade = simulate_trade(df, symbol, strategy, rec)
                if trade is not None:
                    all_trades[strategy].append(trade)

    summary = {
        "methodology": {
            "timeframe": "H1",
            "symbols": SYMBOLS,
            "source": SOURCE,
            "balanced_sample": "25 completed trades per each of 4 PIT regimes = 100 per strategy",
            "regimes": REGIMES,
            "max_hold_bars": MAX_HOLD_BARS,
            "same_bar_policy": "STOP_FIRST",
            "costs": "observed MT5 spread converted to price/risk + 0.02R slippage/commission allowance",
            "note": "signal-level research benchmark; no broker execution and no portfolio-overlap constraint",
        },
        "coverage": coverage,
        "strategies": {},
    }
    all_rows = []
    balanced_rows = []
    for strategy in strategies:
        df = pd.DataFrame(all_trades[strategy])
        if not df.empty:
            df = df.sort_values(["entry_at", "symbol"]).reset_index(drop=True)
            all_rows.append(df)
        sample, candidate_counts = stratified_100(df)
        if not sample.empty:
            balanced_rows.append(sample)
        summary["strategies"][strategy] = {
            "candidate_completed_trades": int(len(df)),
            "candidate_counts_by_regime": candidate_counts,
            "all_sample_metrics": metrics(df),
            "balanced_100_metrics": metrics(sample),
            "balanced_100_by_regime": {r: metrics(sample[sample.regime == r]) for r in REGIMES} if not sample.empty else {},
            "monte_carlo_balanced_100": monte_carlo(sample),
            "coverage_pass_100": bool(len(sample) == 100),
        }

    ranking = []
    for strategy, row in summary["strategies"].items():
        m = row["balanced_100_metrics"]
        if row["coverage_pass_100"]:
            ranking.append(
                {
                    "strategy": strategy,
                    "total_net_r": m["total_net_r"],
                    "avg_net_r": m["avg_net_r"],
                    "profit_factor": m["profit_factor"],
                    "win_rate": m["win_rate"],
                    "max_drawdown_r": m["max_drawdown_r"],
                    "mc_prob_positive": row["monte_carlo_balanced_100"].get("prob_total_net_r_positive"),
                }
            )
    ranking = sorted(ranking, key=lambda r: (r["total_net_r"], r["avg_net_r"]), reverse=True)
    summary["ranking_balanced_100"] = ranking

    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if all_rows:
        pd.concat(all_rows, ignore_index=True).to_csv(outdir / "all_completed_trades.csv", index=False)
    if balanced_rows:
        pd.concat(balanced_rows, ignore_index=True).to_csv(outdir / "balanced_100_trades.csv", index=False)

    lines = [
        "# Forex Strategy Regime Benchmark — 100 Trades Each",
        "",
        "Balanced sample: 25 trades from each of TREND_HIGH_VOL, TREND_LOW_VOL, RANGE_HIGH_VOL, RANGE_LOW_VOL.",
        "All entries use only information available at the signal bar; entry is next-bar open. Same-bar SL/TP ambiguity is STOP_FIRST.",
        "",
        "| Rank | Strategy | Trades | Net R | Avg R | Win % | PF | Max DD (R) | MC P(positive) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(ranking, 1):
        pf = "NA" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
        lines.append(
            f"| {rank} | {row['strategy']} | 100 | {row['total_net_r']:.2f} | {row['avg_net_r']:.3f} | "
            f"{100*row['win_rate']:.1f}% | {pf} | {row['max_drawdown_r']:.2f} | {100*row['mc_prob_positive']:.1f}% |"
        )
    lines += ["", "## Coverage / full-sample check", ""]
    for strategy in strategies:
        row = summary["strategies"][strategy]
        fm = row["all_sample_metrics"]
        lines.append(
            f"- **{strategy}**: candidates={row['candidate_completed_trades']}; coverage100={row['coverage_pass_100']}; "
            f"full avgR={fm.get('avg_net_r', float('nan')):.3f}; full PF={fm.get('profit_factor')}"
        )
    (outdir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((outdir / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD")
SOURCE = "https://raw.githubusercontent.com/ejtraderLabs/historical-data/main/{pair}/{pair}h1.csv"
BASE_COST_PIPS = 1.2
TRAIN_END = pd.Timestamp("2017-12-31 23:59:59")
VALIDATION_END = pd.Timestamp("2019-12-31 23:59:59")
MIN_TRAIN = 50
MIN_VALIDATION = 20
SEED = 20260911


@dataclass(frozen=True)
class Spec:
    name: str
    stop_atr: float
    target_atr: float
    max_hold: int


SPECS = {
    "DONCHIAN20": Spec("DONCHIAN20", 1.50, 2.50, 72),
    "EMA_PULLBACK": Spec("EMA_PULLBACK", 1.25, 2.00, 48),
    "MOMENTUM24": Spec("MOMENTUM24", 1.75, 3.00, 96),
    "MEAN_REVERT": Spec("MEAN_REVERT", 1.25, 1.25, 24),
}


def load_pair(pair: str) -> pd.DataFrame:
    df = pd.read_csv(SOURCE.format(pair=pair))
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date") or df.columns[0]
    df["time"] = pd.to_datetime(df[date_col], utc=True, errors="coerce").dt.tz_convert(None)
    for c in ("open", "high", "low", "close"):
        src = cols.get(c)
        if not src:
            raise ValueError(f"{pair}: missing {c}")
        df[c] = pd.to_numeric(df[src], errors="coerce")
    df = df[["time", "open", "high", "low", "close"]].dropna().drop_duplicates("time").sort_values("time")
    return df.reset_index(drop=True)


def rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    pc = x["close"].shift(1)
    tr = pd.concat(
        [(x["high"] - x["low"]).abs(), (x["high"] - pc).abs(), (x["low"] - pc).abs()], axis=1
    ).max(axis=1)
    x["atr14"] = rma(tr, 14)
    up = x["high"].diff()
    dn = -x["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=x.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=x.index)
    plus_di = 100 * rma(plus_dm, 14) / x["atr14"].replace(0, np.nan)
    minus_di = 100 * rma(minus_dm, 14) / x["atr14"].replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["adx14"] = rma(dx, 14)
    x["ema20"] = x["close"].ewm(span=20, adjust=False).mean()
    x["ema50"] = x["close"].ewm(span=50, adjust=False).mean()
    x["ema200"] = x["close"].ewm(span=200, adjust=False).mean()
    delta = x["close"].diff()
    gain = pd.Series(np.where(delta > 0, delta, 0.0), index=x.index)
    loss = pd.Series(np.where(delta < 0, -delta, 0.0), index=x.index)
    rs = rma(gain, 14) / rma(loss, 14).replace(0, np.nan)
    x["rsi14"] = 100 - 100 / (1 + rs)
    mid = x["close"].rolling(20).mean()
    sd = x["close"].rolling(20).std(ddof=0)
    x["bb_lo"] = mid - 2 * sd
    x["bb_hi"] = mid + 2 * sd
    x["don_hi"] = x["high"].rolling(20).max().shift(1)
    x["don_lo"] = x["low"].rolling(20).min().shift(1)
    x["ret24"] = x["close"].pct_change(24)
    x["abs_ret24_med"] = x["ret24"].abs().rolling(500).median().shift(1)
    x["atr_rel"] = x["atr14"] / x["close"].abs().replace(0, np.nan)
    x["atr_rel_med"] = x["atr_rel"].rolling(500).median().shift(1)
    trend = x["adx14"] >= 25
    high_vol = x["atr_rel"] > x["atr_rel_med"]
    x["regime"] = np.select(
        [trend & high_vol, trend & ~high_vol, ~trend & high_vol, ~trend & ~high_vol],
        ["TREND_HIGH_VOL", "TREND_LOW_VOL", "RANGE_HIGH_VOL", "RANGE_LOW_VOL"],
        default="UNKNOWN",
    )
    return x


def infer_pip_raw(pair: str, df: pd.DataFrame) -> float:
    med = float(df["close"].median())
    if pair.endswith("JPY"):
        scale = 1000.0 if med > 1000 else 1.0
        return 0.01 * scale
    scale = 100000.0 if med > 1000 else 1.0
    return 0.0001 * scale


def signals(x: pd.DataFrame, name: str) -> pd.Series:
    sig = pd.Series(0, index=x.index, dtype="int8")
    if name == "DONCHIAN20":
        sig[x["close"] > x["don_hi"]] = 1
        sig[x["close"] < x["don_lo"]] = -1
    elif name == "EMA_PULLBACK":
        long = (
            (x["ema50"] > x["ema200"])
            & (x["low"] <= x["ema20"])
            & (x["close"] > x["ema20"])
            & (x["close"].shift(1) <= x["ema20"].shift(1))
        )
        short = (
            (x["ema50"] < x["ema200"])
            & (x["high"] >= x["ema20"])
            & (x["close"] < x["ema20"])
            & (x["close"].shift(1) >= x["ema20"].shift(1))
        )
        sig[long] = 1
        sig[short] = -1
    elif name == "MOMENTUM24":
        strong = x["ret24"].abs() > x["abs_ret24_med"]
        sig[(x["ret24"] > 0) & (x["close"] > x["ema200"]) & strong] = 1
        sig[(x["ret24"] < 0) & (x["close"] < x["ema200"]) & strong] = -1
    elif name == "MEAN_REVERT":
        sig[(x["rsi14"] < 30) & (x["close"] < x["bb_lo"])] = 1
        sig[(x["rsi14"] > 70) & (x["close"] > x["bb_hi"])] = -1
    return sig


def simulate_strategy(pair: str, x: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    sig = signals(x, spec.name)
    pip_raw = infer_pip_raw(pair, x)
    rows: list[dict] = []
    for i in np.flatnonzero(sig.to_numpy() != 0):
        if i + 1 >= len(x) or not np.isfinite(x.at[i, "atr14"]) or x.at[i, "regime"] == "UNKNOWN":
            continue
        direction = int(sig.iat[i])
        entry_i = i + 1
        entry = float(x.at[entry_i, "open"])
        atr = float(x.at[i, "atr14"])
        stop_dist = spec.stop_atr * atr
        if stop_dist <= 0:
            continue
        target_dist = spec.target_atr * atr
        stop = entry - direction * stop_dist
        target = entry + direction * target_dist
        exit_i = min(entry_i + spec.max_hold, len(x) - 1)
        gross_r = None
        reason = "TIME"
        for j in range(entry_i, exit_i + 1):
            lo, hi = float(x.at[j, "low"]), float(x.at[j, "high"])
            stop_hit = lo <= stop if direction > 0 else hi >= stop
            target_hit = hi >= target if direction > 0 else lo <= target
            # Deliberately conservative: stop wins all same-H1-bar SL/TP ambiguities.
            if stop_hit:
                exit_i, gross_r, reason = j, -1.0, "STOP"
                break
            if target_hit:
                exit_i, gross_r, reason = j, target_dist / stop_dist, "TARGET"
                break
        if gross_r is None:
            exit_px = float(x.at[exit_i, "close"])
            gross_r = direction * (exit_px - entry) / stop_dist
        cost_r = BASE_COST_PIPS * pip_raw / stop_dist
        rows.append(
            {
                "pair": pair,
                "strategy": spec.name,
                "signal_time": x.at[i, "time"],
                "entry_time": x.at[entry_i, "time"],
                "exit_time": x.at[exit_i, "time"],
                "regime": x.at[i, "regime"],
                "direction": direction,
                "gross_r": gross_r,
                "cost_r": cost_r,
                "net_r": gross_r - cost_r,
                "exit_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def split_name(t: pd.Timestamp) -> str:
    if t <= TRAIN_END:
        return "TRAIN"
    if t <= VALIDATION_END:
        return "VALIDATION"
    return "OOS"


def metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": None,
            "win_rate": None,
            "profit_factor": None,
            "max_dd_r": None,
            "ci95_lo": None,
            "ci95_hi": None,
        }
    y = df.sort_values(["entry_time", "pair"])["net_r"].to_numpy(float)
    eq = np.cumsum(y)
    peak = np.maximum.accumulate(np.r_[0.0, eq])
    dd = peak[1:] - eq
    gp = y[y > 0].sum()
    gl = -y[y < 0].sum()
    rng = np.random.default_rng(SEED)
    means = np.empty(1000)
    for k in range(1000):
        means[k] = rng.choice(y, size=len(y), replace=True).mean()
    return {
        "trades": int(len(y)),
        "net_r": round(float(y.sum()), 4),
        "expectancy_r": round(float(y.mean()), 5),
        "win_rate": round(float((y > 0).mean()), 4),
        "profit_factor": None if gl <= 0 else round(float(gp / gl), 4),
        "max_dd_r": round(float(dd.max() if len(dd) else 0.0), 4),
        "ci95_lo": round(float(np.quantile(means, 0.025)), 5),
        "ci95_hi": round(float(np.quantile(means, 0.975)), 5),
    }


def nonoverlap(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    chosen = []
    for _, g in df.sort_values(["entry_time", "strategy"]).groupby("pair"):
        free_at = pd.Timestamp.min
        for _, row in g.iterrows():
            if row["entry_time"] >= free_at:
                chosen.append(row)
                free_at = row["exit_time"]
    return pd.DataFrame(chosen).reset_index(drop=True) if chosen else df.iloc[0:0].copy()


def choose_mapping(trades: pd.DataFrame, keys: list[str]) -> dict:
    train = trades[trades["split"] == "TRAIN"]
    val = trades[trades["split"] == "VALIDATION"]
    mapping = {}
    for vals in train[keys].drop_duplicates().itertuples(index=False, name=None):
        qtr, qv = train, val
        for key, value in zip(keys, vals):
            qtr = qtr[qtr[key] == value]
            qv = qv[qv[key] == value]
        candidates = []
        for strategy in SPECS:
            a = qtr[qtr["strategy"] == strategy]
            b = qv[qv["strategy"] == strategy]
            if (
                len(a) >= MIN_TRAIN
                and len(b) >= MIN_VALIDATION
                and a["net_r"].mean() > 0
                and b["net_r"].mean() > 0
            ):
                # Validation is only a gate. Strategy ranking is frozen on TRAIN expectancy.
                candidates.append((float(a["net_r"].mean()), strategy))
        mapping[vals] = max(candidates)[1] if candidates else "NO_TRADE"
    return mapping


def apply_mapping(oos: pd.DataFrame, keys: list[str], mapping: dict) -> pd.DataFrame:
    parts = []
    for vals, strategy in mapping.items():
        if strategy == "NO_TRADE":
            continue
        q = oos[oos["strategy"] == strategy]
        for key, value in zip(keys, vals):
            q = q[q[key] == value]
        parts.append(q)
    return nonoverlap(pd.concat(parts, ignore_index=True)) if parts else oos.iloc[0:0].copy()


def annual_stability(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"positive_years": 0, "years": 0, "annual_net_r": {}}
    z = df.assign(year=pd.DatetimeIndex(df["entry_time"]).year).groupby("year")["net_r"].sum()
    return {
        "positive_years": int((z > 0).sum()),
        "years": int(len(z)),
        "annual_net_r": {str(int(k)): round(float(v), 3) for k, v in z.items()},
    }


def main() -> None:
    all_parts = []
    coverage = {}
    for pair in PAIRS:
        raw = load_pair(pair)
        coverage[pair] = {
            "rows": len(raw),
            "start": str(raw["time"].min()),
            "end": str(raw["time"].max()),
        }
        x = add_indicators(raw)
        for spec in SPECS.values():
            all_parts.append(simulate_strategy(pair, x, spec))
    trades = pd.concat(all_parts, ignore_index=True)
    trades["split"] = trades["signal_time"].map(split_name)
    oos = trades[trades["split"] == "OOS"].copy()

    systems = {}
    for strategy in SPECS:
        d = nonoverlap(oos[oos["strategy"] == strategy])
        systems[f"STATIC_{strategy}"] = {**metrics(d), **annual_stability(d)}

    pair_map = choose_mapping(trades, ["pair"])
    pair_oos = apply_mapping(oos, ["pair"], pair_map)
    systems["PAIR_ROUTER"] = {**metrics(pair_oos), **annual_stability(pair_oos)}

    regime_map = choose_mapping(trades, ["regime"])
    regime_oos = apply_mapping(oos, ["regime"], regime_map)
    systems["REGIME_ROUTER"] = {**metrics(regime_oos), **annual_stability(regime_oos)}

    pair_regime_map = choose_mapping(trades, ["pair", "regime"])
    pair_regime_oos = apply_mapping(oos, ["pair", "regime"], pair_regime_map)
    systems["PAIR_REGIME_ROUTER"] = {**metrics(pair_regime_oos), **annual_stability(pair_regime_oos)}

    result = {
        "contract": "ADAPTIVE_PUBLIC_RESEARCH_V1",
        "execution_influence": False,
        "source": SOURCE,
        "pairs": list(PAIRS),
        "timeframe": "H1",
        "cost_pips_roundtrip": BASE_COST_PIPS,
        "splits": {
            "train_end": str(TRAIN_END),
            "validation_end": str(VALIDATION_END),
            "oos_start": "2020-01-01",
        },
        "regime": "ADX14>=25 => TREND; ATR14/close above lagged rolling-500 median => HIGH_VOL",
        "selection_rule": (
            f"train n>={MIN_TRAIN}, validation n>={MIN_VALIDATION}, positive expectancy in both; "
            "rank by TRAIN expectancy only; otherwise NO_TRADE"
        ),
        "same_bar_policy": "STOP_FIRST",
        "coverage": coverage,
        "systems": systems,
        "pair_map": {"|".join(k): v for k, v in pair_map.items()},
        "regime_map": {"|".join(k): v for k, v in regime_map.items()},
        "pair_regime_map": {"|".join(k): v for k, v in pair_regime_map.items()},
    }

    out = Path("research_output")
    out.mkdir(exist_ok=True)
    (out / "adaptive_public_v1.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    trades.to_csv(out / "adaptive_public_v1_all_candidate_trades.csv", index=False)

    ranking = sorted(
        systems.items(),
        key=lambda kv: -999 if kv[1]["expectancy_r"] is None else kv[1]["expectancy_r"],
        reverse=True,
    )
    lines = [
        "# Adaptive Public Research V1",
        "",
        "Research-only. No execution influence. Final OOS begins 2020-01-01.",
        "",
        "| System | Trades | Net R | Exp R | PF | Win rate | Max DD R | 95% bootstrap mean CI |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in ranking:
        ci = f'{m["ci95_lo"]}..{m["ci95_hi"]}' if m["ci95_lo"] is not None else "N/A"
        lines.append(
            f'| {name} | {m["trades"]} | {m["net_r"]} | {m["expectancy_r"]} | '
            f'{m["profit_factor"]} | {m["win_rate"]} | {m["max_dd_r"]} | {ci} |'
        )
    lines += [
        "",
        "## Frozen pair x regime map",
        "",
        "```json",
        json.dumps(result["pair_regime_map"], indent=2),
        "```",
        "",
    ]
    (out / "adaptive_public_v1.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

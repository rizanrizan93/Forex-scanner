from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pandas as pd

import four_pair_strategy_search_v1 as v1
import four_pair_strategy_search_v2 as v2

CONTRACT = "FOUR_PAIR_CAUSAL_ADAPTIVE_V3"
EXECUTION_INFLUENCE = False
MIN_SHORT = 12
LONG_WINDOW = 24

# Frozen before this replay: identical causal rule for all pairs. It may consume
# completed shadow outcomes from candidate families, but never future outcomes.
PAIR_POOL = {
    "USDJPY": (
        "D1_DONCHIAN55_200",
        "D1_TSMOM_60_200",
        "H4_COMPRESSION20_TREND",
        "D1_TSMOM_252_CHANDELIER3",
    ),
    "GBPUSD": (
        "H4_MEAN_REVERT_Z2_TO_SMA20",
        "H4_DONCHIAN40_CHANDELIER3",
        "H4_DONCHIAN40_ADX20",
        "H1_ASIA_LONDON_BREAKOUT_TREND",
    ),
    "EURUSD": (
        "H4_MEAN_REVERT_Z2_TO_SMA20",
        "H4_MEAN_REVERT_Z175_TO_SMA20",
        "D1_TSMOM_60_200",
        "D1_TSMOM_252_CHANDELIER3",
    ),
    "AUDUSD": (
        "H4_MEAN_REVERT_Z2_TO_SMA20",
        "H4_PULLBACK_ADX20",
        "D1_TSMOM_120_200",
        "D1_TSMOM_252_CHANDELIER3",
    ),
}


def pf(values: pd.Series) -> float:
    pos = float(values[values > 0].sum())
    neg = float(-values[values < 0].sum())
    return pos / neg if neg > 0 else (999.0 if pos > 0 else 0.0)


def build_pool(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    a = v1.generate(symbol, h1)
    b = v2.generate(symbol, h1)
    all_frames = {**a, **b}
    missing = [name for name in PAIR_POOL[symbol] if name not in all_frames]
    if missing:
        raise RuntimeError(f"{symbol}: missing pool frames {missing}")
    return {name: all_frames[name].copy() for name in PAIR_POOL[symbol]}


def shadow_net(frame: pd.DataFrame, symbol: str) -> pd.Series:
    return v1.repriced(frame, symbol, 2.0)


def evidence_before(frame: pd.DataFrame, symbol: str, at: pd.Timestamp) -> dict | None:
    hist = frame[pd.to_datetime(frame["exit_time"], utc=True) < at].copy()
    if len(hist) < MIN_SHORT:
        return None
    short = hist.tail(MIN_SHORT)
    short_net = shadow_net(short, symbol)
    short_exp = float(short_net.mean())
    short_pf = pf(short_net)
    if len(hist) >= LONG_WINDOW:
        long_net = shadow_net(hist.tail(LONG_WINDOW), symbol)
        long_exp = float(long_net.mean())
    else:
        long_exp = short_exp
    enabled = short_exp > 0.0 and short_pf > 1.0 and long_exp > 0.0
    return {
        "enabled": enabled,
        "history_n": int(len(hist)),
        "short_expectancy": short_exp,
        "short_pf": short_pf,
        "long_expectancy": long_exp,
        "score": short_exp + 0.5 * long_exp + 0.02 * math.log(max(short_pf, 1e-9)),
    }


def route(symbol: str, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    events = []
    for strategy, frame in frames.items():
        if frame.empty:
            continue
        for idx, row in frame.iterrows():
            events.append((pd.Timestamp(row["signal_time"]), strategy, int(idx)))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    accepted = []
    open_until = pd.Timestamp("1900-01-01", tz="UTC")
    i = 0
    while i < len(events):
        at = events[i][0]
        same = []
        while i < len(events) and events[i][0] == at:
            same.append(events[i])
            i += 1
        if at <= open_until:
            continue
        choices = []
        for _, strategy, idx in same:
            frame = frames[strategy]
            ev = evidence_before(frame, symbol, at)
            if not ev or not ev["enabled"]:
                continue
            row = frame.loc[idx].copy()
            choices.append((float(ev["score"]), strategy, row, ev))
        if not choices:
            continue
        choices.sort(key=lambda x: (x[0], x[1]), reverse=True)
        score, strategy, row, ev = choices[0]
        row["strategy"] = f"ADAPTIVE::{strategy}"
        row["adaptive_source_strategy"] = strategy
        row["adaptive_score"] = score
        row["adaptive_short_expectancy"] = ev["short_expectancy"]
        row["adaptive_short_pf"] = ev["short_pf"]
        row["adaptive_long_expectancy"] = ev["long_expectancy"]
        row["adaptive_history_n"] = ev["history_n"]
        accepted.append(row)
        open_until = pd.Timestamp(row["exit_time"])
    return pd.DataFrame(accepted).reset_index(drop=True) if accepted else pd.DataFrame()


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in v1.SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(v1.SYMBOLS)}")
    print(f"FETCH {symbol} V3 causal adaptive public Dukascopy BID H1")
    h1 = v1.fetch_h1(symbol)
    frames = build_pool(symbol, h1)
    routed = route(symbol, frames)
    assessment = v1.assess(symbol, "CAUSAL_ADAPTIVE_ROUTER_V3", routed)
    sources = {}
    if not routed.empty:
        sources = {str(k): int(v) for k, v in routed["adaptive_source_strategy"].value_counts().items()}
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": symbol,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "data_start": str(v1.DATA_START.date()),
        "data_end_exclusive": str(v1.DATA_END.date()),
        "same_bar_policy": v1.SAME_BAR_POLICY,
        "pool": list(PAIR_POOL[symbol]),
        "causal_rule": {
            "short_window_completed_shadow_trades": MIN_SHORT,
            "long_window_completed_shadow_trades": LONG_WINDOW,
            "enable_if": "short expectancy > 0 AND short PF > 1 AND long expectancy > 0 at 2-pip stress; all outcomes must have exited before current signal",
            "pair_non_overlap": True,
            "selection_if_simultaneous": "highest frozen causal score",
        },
        "coverage": {"h1_rows": int(len(h1)), "h1_start": str(h1.time.min()), "h1_end": str(h1.time.max())},
        "assessment": assessment,
        "accepted_source_counts": sources,
    }
    out = Path("research_output_four_pair_v3")
    out.mkdir(exist_ok=True)
    (out / f"four_pair_adaptive_v3_{symbol}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    routed.to_csv(out / f"{symbol}_adaptive_v3_trades.csv", index=False)
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    s = assessment["stress_2p0"]
    print("ADAPTIVE", json.dumps({
        "symbol": symbol,
        "status": assessment["status"],
        "trades": s["trades"],
        "expectancy_r": s["expectancy_r"],
        "pf": s["profit_factor"],
        "net_r": s["net_r"],
        "max_dd_r": s["max_dd_r"],
        "ci_low": s["bootstrap_ci_low"],
        "ci_high": s["bootstrap_ci_high"],
        "positive_eras": assessment["positive_eras_stress_2pip"],
        "recent_exp": assessment["eras_stress_2p0"]["2024_2026"]["expectancy_r"],
        "recent_pf": assessment["eras_stress_2p0"]["2024_2026"]["profit_factor"],
        "sources": sources,
    }, sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()

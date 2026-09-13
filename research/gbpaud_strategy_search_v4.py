from __future__ import annotations

"""Fourth-stage GBPAUD strategy search, research-only.

This tournament intentionally changes strategy families rather than retuning the failed V2/V3
champions. The frozen set includes daily short-horizon breakout, daily pullback resumption,
H4 volatility expansion, H4 squeeze breakout, and two H1 session/range breakout families.
No execution path or promotion authority is present.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2
import remaining_fx_pair_strategy_search_v1 as remaining

CONTRACT = "GBPAUD_STRATEGY_SEARCH_V4"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
SYMBOL = "GBPAUD"

CANDIDATES = (
    "D1_DONCHIAN20_ADX20_CHANDELIER3",
    "D1_PULLBACK_EMA20_ADX25_CHANDELIER3",
    "H4_VOL_EXPANSION_DONCHIAN24_RR2",
    "H4_BB_SQUEEZE_BREAKOUT_RR2",
    "H1_ASIA_LONDON_BREAKOUT_RR2",
    "H1_PREVDAY_LONDON_BREAKOUT_RR2",
)


def _rolling_quantile(values: pd.Series, window: int, q: float) -> pd.Series:
    return values.rolling(window).quantile(q)


def _simulate_fixed_rr(
    symbol: str,
    strategy: str,
    frame: pd.DataFrame,
    direction: pd.Series,
    *,
    stop_atr: float,
    target_r: float,
    max_hold: int,
) -> pd.DataFrame:
    x = frame.reset_index(drop=True)
    dirs = direction.fillna(0).astype(int).to_numpy()
    rows: list[dict] = []
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
        entry_i = i + 1
        entry = float(x.loc[entry_i, "open"])
        risk = stop_atr * atr0
        stop = entry - d * risk
        target = entry + d * target_r * risk
        last = min(len(x) - 1, entry_i + max_hold - 1)
        exit_i = last
        exit_px = float(x.loc[last, "close"])
        reason = "TIME"
        for j in range(entry_i, last + 1):
            o, hi, lo = (float(x.loc[j, k]) for k in ("open", "high", "low"))
            if d > 0:
                if o <= stop:
                    exit_i, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o >= target:
                    exit_i, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = lo <= stop, hi >= target
            else:
                if o >= stop:
                    exit_i, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o <= target:
                    exit_i, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = hi >= stop, lo <= target
            if stop_hit:  # Conservative same-bar policy.
                exit_i, exit_px, reason = j, stop, "STOP"
                break
            if target_hit:
                exit_i, exit_px, reason = j, target, "TARGET"
                break
        gross_r = d * (exit_px - entry) / risk
        rows.append(
            base.trade_record(
                symbol,
                strategy,
                x.loc[i, "time"],
                x.loc[entry_i, "time"],
                x.loc[exit_i, "time"],
                d,
                entry,
                risk,
                gross_r,
                reason,
            )
        )
        i = exit_i + 1
    return pd.DataFrame(rows)


def _d1_donchian20(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "1D")).copy()
    prior_high20 = x["high"].rolling(20).max().shift(1)
    prior_low20 = x["low"].rolling(20).min().shift(1)
    long_sig = (
        (x["close"] > x["ema200"])
        & (x["adx14"] >= 20.0)
        & (x["close"] > prior_high20)
    )
    short_sig = (
        (x["close"] < x["ema200"])
        & (x["adx14"] >= 20.0)
        & (x["close"] < prior_low20)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        symbol,
        "D1_DONCHIAN20_ADX20_CHANDELIER3",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=3.0,
        max_hold=100,
    )


def _d1_pullback(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "1D")).copy()
    prev_close = x["close"].shift(1)
    prev_ema20 = x["ema20"].shift(1)
    long_sig = (
        (x["ema50"] > x["ema200"])
        & (x["adx14"] >= 25.0)
        & (prev_close <= prev_ema20)
        & (x["close"] > x["ema20"])
        & (x["rsi14"] >= 45.0)
        & (x["rsi14"] <= 68.0)
    )
    short_sig = (
        (x["ema50"] < x["ema200"])
        & (x["adx14"] >= 25.0)
        & (prev_close >= prev_ema20)
        & (x["close"] < x["ema20"])
        & (x["rsi14"] <= 55.0)
        & (x["rsi14"] >= 32.0)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        symbol,
        "D1_PULLBACK_EMA20_ADX25_CHANDELIER3",
        x,
        direction,
        initial_stop_atr=1.75,
        trail_atr=3.0,
        max_hold=80,
    )


def _h4_vol_expansion(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "4h")).copy()
    prior_high = x["high"].rolling(24).max().shift(1)
    prior_low = x["low"].rolling(24).min().shift(1)
    atr_pct = x["atr14"] / x["close"].replace(0, np.nan)
    atr_med = atr_pct.rolling(126).median()
    long_sig = (
        (x["ema50"] > x["ema200"])
        & (x["adx14"] >= 25.0)
        & (atr_pct >= atr_med)
        & (x["close"] > prior_high)
    )
    short_sig = (
        (x["ema50"] < x["ema200"])
        & (x["adx14"] >= 25.0)
        & (atr_pct >= atr_med)
        & (x["close"] < prior_low)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr(
        symbol,
        "H4_VOL_EXPANSION_DONCHIAN24_RR2",
        x,
        direction,
        stop_atr=1.5,
        target_r=2.0,
        max_hold=30,
    )


def _h4_squeeze_breakout(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "4h")).copy()
    mean = x["close"].rolling(20).mean()
    std = x["close"].rolling(20).std(ddof=0)
    upper = mean + 2.0 * std
    lower = mean - 2.0 * std
    bandwidth = (upper - lower) / mean.replace(0, np.nan)
    squeeze_cutoff = _rolling_quantile(bandwidth, 120, 0.30)
    was_squeezed = bandwidth.shift(1) <= squeeze_cutoff.shift(1)
    long_sig = (
        was_squeezed
        & (x["ema50"] > x["ema200"])
        & (x["close"] > upper)
        & (x["adx14"] >= 18.0)
    )
    short_sig = (
        was_squeezed
        & (x["ema50"] < x["ema200"])
        & (x["close"] < lower)
        & (x["adx14"] >= 18.0)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr(
        symbol,
        "H4_BB_SQUEEZE_BREAKOUT_RR2",
        x,
        direction,
        stop_atr=1.5,
        target_r=2.0,
        max_hold=24,
    )


def _h1_with_session_features(h1: pd.DataFrame) -> pd.DataFrame:
    x = base.indicators(h1.copy()).copy()
    t = pd.to_datetime(x["time"], utc=True)
    x["date"] = t.dt.floor("D")
    x["hour"] = t.dt.hour

    asia = x.loc[x["hour"].between(0, 5)].groupby("date").agg(
        asia_high=("high", "max"), asia_low=("low", "min")
    )
    prior_day = x.groupby("date").agg(day_high=("high", "max"), day_low=("low", "min")).shift(1)
    x = x.merge(asia, left_on="date", right_index=True, how="left")
    x = x.merge(prior_day, left_on="date", right_index=True, how="left")
    return x


def _h1_asia_london(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = _h1_with_session_features(h1)
    london = x["hour"].between(7, 11)
    long_sig = (
        london
        & (x["close"] > x["ema200"])
        & (x["close"] > x["asia_high"])
        & (x["close"].shift(1) <= x["asia_high"].shift(1))
    )
    short_sig = (
        london
        & (x["close"] < x["ema200"])
        & (x["close"] < x["asia_low"])
        & (x["close"].shift(1) >= x["asia_low"].shift(1))
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr(
        symbol,
        "H1_ASIA_LONDON_BREAKOUT_RR2",
        x,
        direction,
        stop_atr=1.25,
        target_r=2.0,
        max_hold=10,
    )


def _h1_prevday_london(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = _h1_with_session_features(h1)
    london_ny = x["hour"].between(7, 15)
    long_sig = (
        london_ny
        & (x["ema50"] > x["ema200"])
        & (x["close"] > x["day_high"])
        & (x["close"].shift(1) <= x["day_high"].shift(1))
    )
    short_sig = (
        london_ny
        & (x["ema50"] < x["ema200"])
        & (x["close"] < x["day_low"])
        & (x["close"].shift(1) >= x["day_low"].shift(1))
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr(
        symbol,
        "H1_PREVDAY_LONDON_BREAKOUT_RR2",
        x,
        direction,
        stop_atr=1.5,
        target_r=2.0,
        max_hold=12,
    )


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "D1_DONCHIAN20_ADX20_CHANDELIER3": _d1_donchian20(symbol, h1),
        "D1_PULLBACK_EMA20_ADX25_CHANDELIER3": _d1_pullback(symbol, h1),
        "H4_VOL_EXPANSION_DONCHIAN24_RR2": _h4_vol_expansion(symbol, h1),
        "H4_BB_SQUEEZE_BREAKOUT_RR2": _h4_squeeze_breakout(symbol, h1),
        "H1_ASIA_LONDON_BREAKOUT_RR2": _h1_asia_london(symbol, h1),
        "H1_PREVDAY_LONDON_BREAKOUT_RR2": _h1_prevday_london(symbol, h1),
    }
    return {name: frames[name] for name in CANDIDATES}


def main() -> None:
    remaining.install_instrument(SYMBOL)
    print(f"FETCH {SYMBOL} V4 public Dukascopy BID H1")
    h1 = base.fetch_h1(SYMBOL)
    print(f"COVERAGE rows={len(h1)} start={h1.time.min()} end={h1.time.max()}")

    frames = generate(SYMBOL, h1)
    scorecard = [remaining.assess(SYMBOL, name, trades) for name, trades in frames.items()]
    rank = {"STRONG_RESEARCH_PASS": 2, "WATCH": 1, "REJECT": 0}
    scorecard.sort(
        key=lambda row: (
            rank[row["status"]],
            row["stress"]["expectancy_r"],
            row["stress"]["profit_factor"],
        ),
        reverse=True,
    )
    champion = scorecard[0]
    base_cost, stress_cost, severe_cost = remaining.COSTS[SYMBOL]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "symbol": SYMBOL,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "data_start": str(base.DATA_START.date()),
        "data_end_exclusive": str(base.DATA_END.date()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "cost_model_pips": {
            "base": base_cost,
            "stress": stress_cost,
            "severe": severe_cost,
        },
        "research_change": (
            "Frozen V4 family shift after broker rejection of D1 TSMOM180 and H4 Z2 mean reversion: "
            "short-horizon D1 breakout/pullback, H4 volatility/squeeze breakouts, and H1 session/range breakouts."
        ),
        "candidate_set": list(CANDIDATES),
        "coverage": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1.time.min()),
            "h1_end": str(h1.time.max()),
        },
        "champion_by_rule": {"strategy": champion["strategy"], "status": champion["status"]},
        "scorecard": scorecard,
    }

    out = Path("research_output_gbpaud_v4")
    out.mkdir(exist_ok=True)
    (out / "gbpaud_strategy_search_v4.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, trades in frames.items():
        trades.to_csv(out / f"{SYMBOL}_{name}_trades.csv", index=False)

    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        stress = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print(
            "V4_SCORE "
            + json.dumps(
                {
                    "strategy": row["strategy"],
                    "status": row["status"],
                    "trades": stress["trades"],
                    "expectancy_r": stress["expectancy_r"],
                    "pf": stress["profit_factor"],
                    "net_r": stress["net_r"],
                    "max_dd_r": stress["max_dd_r"],
                    "positive_eras": row["positive_eras"],
                    "ci_low": stress["bootstrap_ci_low"],
                    "ci_high": stress["bootstrap_ci_high"],
                    "recent_exp": recent["expectancy_r"],
                    "recent_pf": recent["profit_factor"],
                },
                sort_keys=True,
            )
        )
    print("Research only: execution_influence=false promotion_authority=false")


if __name__ == "__main__":
    main()

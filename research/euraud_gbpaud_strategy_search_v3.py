from __future__ import annotations

"""Third-stage, research-only search for EURAUD and GBPAUD.

The candidate family is frozen before execution and deliberately compact. It adds:
- slower/wider daily time-series momentum,
- volatility-confirmed daily Donchian breakout,
- H4 trend-pullback resumption,
- stricter low-ADX mean reversion.

This module has no order path, execution influence, or promotion authority.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2
import remaining_fx_pair_strategy_search_v1 as remaining

CONTRACT = "EURAUD_GBPAUD_STRATEGY_SEARCH_V3"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
SYMBOLS = ("EURAUD", "GBPAUD")

CANDIDATES = (
    "D1_TSMOM_60_CHANDELIER4",
    "D1_TSMOM_180_CHANDELIER4",
    "D1_DONCHIAN55_VOLFILTER_CHANDELIER35",
    "H4_PULLBACK_EMA20_ADX20_TRAIL25",
    "H4_MEAN_REVERT_Z25_ADX15_SMA20",
    "H4_MEAN_REVERT_Z2_ADX12_SMA20",
)


def _daily_frame(h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "1D")).copy()
    x["ret60"] = x["close"] / x["close"].shift(60) - 1.0
    x["ret180"] = x["close"] / x["close"].shift(180) - 1.0
    x["atr_pct"] = x["atr14"] / x["close"].replace(0, np.nan)
    x["atr_pct_med126"] = x["atr_pct"].rolling(126).median()
    return x


def _d1_tsmom(symbol: str, h1: pd.DataFrame, period: int) -> pd.DataFrame:
    x = _daily_frame(h1)
    ret = x[f"ret{period}"]
    long_sig = (x["close"] > x["ema200"]) & (ret > 0)
    short_sig = (x["close"] < x["ema200"]) & (ret < 0)
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        symbol,
        f"D1_TSMOM_{period}_CHANDELIER4",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=4.0,
        max_hold=160,
    )


def _d1_donchian55_volfilter(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = _daily_frame(h1)
    vol_ok = x["atr_pct"] >= x["atr_pct_med126"]
    long_sig = (
        (x["ema50"] > x["ema200"])
        & vol_ok
        & (x["close"] > x["prior_high55"])
    )
    short_sig = (
        (x["ema50"] < x["ema200"])
        & vol_ok
        & (x["close"] < x["prior_low55"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        symbol,
        "D1_DONCHIAN55_VOLFILTER_CHANDELIER35",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=3.5,
        max_hold=120,
    )


def _h4_pullback_ema20(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, "4h")).copy()
    prev_close = x["close"].shift(1)
    prev_ema20 = x["ema20"].shift(1)

    long_sig = (
        (x["ema50"] > x["ema200"])
        & (x["adx14"] >= 20.0)
        & (prev_close <= prev_ema20)
        & (x["close"] > x["ema20"])
        & (x["rsi14"] >= 45.0)
        & (x["rsi14"] <= 68.0)
    )
    short_sig = (
        (x["ema50"] < x["ema200"])
        & (x["adx14"] >= 20.0)
        & (prev_close >= prev_ema20)
        & (x["close"] < x["ema20"])
        & (x["rsi14"] <= 55.0)
        & (x["rsi14"] >= 32.0)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        symbol,
        "H4_PULLBACK_EMA20_ADX20_TRAIL25",
        x,
        direction,
        initial_stop_atr=1.5,
        trail_atr=2.5,
        max_hold=40,
    )


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "D1_TSMOM_60_CHANDELIER4": _d1_tsmom(symbol, h1, 60),
        "D1_TSMOM_180_CHANDELIER4": _d1_tsmom(symbol, h1, 180),
        "D1_DONCHIAN55_VOLFILTER_CHANDELIER35": _d1_donchian55_volfilter(symbol, h1),
        "H4_PULLBACK_EMA20_ADX20_TRAIL25": _h4_pullback_ema20(symbol, h1),
        "H4_MEAN_REVERT_Z25_ADX15_SMA20": v2.h4_mean_to_sma(
            symbol, h1, 2.5, 15.0, "H4_MEAN_REVERT_Z25_ADX15_SMA20"
        ),
        "H4_MEAN_REVERT_Z2_ADX12_SMA20": v2.h4_mean_to_sma(
            symbol, h1, 2.0, 12.0, "H4_MEAN_REVERT_Z2_ADX12_SMA20"
        ),
    }
    return {name: frames[name] for name in CANDIDATES}


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(SYMBOLS)}")

    remaining.install_instrument(symbol)
    print(f"FETCH {symbol} V3 public Dukascopy BID H1")
    h1 = base.fetch_h1(symbol)
    print(f"COVERAGE rows={len(h1)} start={h1.time.min()} end={h1.time.max()}")

    frames = generate(symbol, h1)
    scorecard = [remaining.assess(symbol, name, trades) for name, trades in frames.items()]
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
    base_cost, stress_cost, severe_cost = remaining.COSTS[symbol]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "symbol": symbol,
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
            "Frozen third-stage family set for EURAUD/GBPAUD: wider daily momentum, "
            "volatility-confirmed Donchian, H4 EMA20 pullback-resumption, and stricter "
            "low-ADX mean reversion. No pair-specific parameter fitting after results."
        ),
        "candidate_set": list(CANDIDATES),
        "coverage": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1.time.min()),
            "h1_end": str(h1.time.max()),
        },
        "champion_by_rule": {
            "strategy": champion["strategy"],
            "status": champion["status"],
        },
        "scorecard": scorecard,
    }

    out = Path("research_output_euraud_gbpaud_v3")
    out.mkdir(exist_ok=True)
    (out / f"euraud_gbpaud_v3_{symbol}.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, trades in frames.items():
        trades.to_csv(out / f"{symbol}_{name}_trades.csv", index=False)

    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        stress = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print(
            "V3_SCORE "
            + json.dumps(
                {
                    "symbol": symbol,
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

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pandas as pd
from dukascopy_python import instruments

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2

CONTRACT = "REMAINING_FX_PAIR_STRATEGY_SEARCH_V1"
EXECUTION_INFLUENCE = False

INSTRUMENT_NAMES = {
    "USDCHF": "INSTRUMENT_FX_MAJORS_USD_CHF",
    "USDCAD": "INSTRUMENT_FX_MAJORS_USD_CAD",
    "NZDUSD": "INSTRUMENT_FX_MAJORS_NZD_USD",
    "EURJPY": "INSTRUMENT_FX_CROSSES_EUR_JPY",
    "GBPJPY": "INSTRUMENT_FX_CROSSES_GBP_JPY",
    "EURGBP": "INSTRUMENT_FX_CROSSES_EUR_GBP",
    "AUDJPY": "INSTRUMENT_FX_CROSSES_AUD_JPY",
    "CADJPY": "INSTRUMENT_FX_CROSSES_CAD_JPY",
    "EURCHF": "INSTRUMENT_FX_CROSSES_EUR_CHF",
    "EURAUD": "INSTRUMENT_FX_CROSSES_EUR_AUD",
    "GBPAUD": "INSTRUMENT_FX_CROSSES_GBP_AUD",
}
SYMBOLS = tuple(INSTRUMENT_NAMES)

# Pair-specific friction assumptions are deliberately more severe for crosses.
# Values are all-in pip proxies applied to every trade, not broker-exact spreads.
COSTS = {
    "USDCHF": (1.2, 2.0, 3.0),
    "USDCAD": (1.2, 2.0, 3.0),
    "NZDUSD": (1.2, 2.0, 3.0),
    "EURJPY": (1.5, 2.5, 4.0),
    "GBPJPY": (2.0, 3.5, 6.0),
    "EURGBP": (1.2, 2.0, 3.0),
    "AUDJPY": (1.5, 3.0, 5.0),
    "CADJPY": (1.5, 3.0, 5.0),
    "EURCHF": (1.5, 2.5, 4.0),
    "EURAUD": (2.0, 3.5, 5.0),
    "GBPAUD": (2.5, 4.0, 6.0),
}

PAIR_CANDIDATES = {
    "USDCHF": ("H4_MEAN_REVERT_Z2_TO_SMA20", "H4_MEAN_REVERT_Z175_TO_SMA20", "D1_DONCHIAN55_200", "D1_TSMOM_60_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20"),
    "USDCAD": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_MEAN_REVERT_Z2_TO_SMA20"),
    "NZDUSD": ("H4_MEAN_REVERT_Z2_TO_SMA20", "H4_MEAN_REVERT_Z175_TO_SMA20", "D1_DONCHIAN55_200", "D1_TSMOM_60_200", "H4_PULLBACK_ADX20", "H4_DONCHIAN40_ADX20"),
    "EURJPY": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_COMPRESSION20_TREND"),
    "GBPJPY": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_COMPRESSION20_TREND"),
    "EURGBP": ("H4_MEAN_REVERT_Z2_TO_SMA20", "H4_MEAN_REVERT_Z175_TO_SMA20", "H4_RSI2_TREND_PULLBACK", "D1_DONCHIAN55_200", "D1_TSMOM_60_200", "H4_COMPRESSION20_TREND"),
    "AUDJPY": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_COMPRESSION20_TREND"),
    "CADJPY": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_COMPRESSION20_TREND"),
    "EURCHF": ("H4_MEAN_REVERT_Z2_TO_SMA20", "H4_MEAN_REVERT_Z175_TO_SMA20", "H4_RSI2_TREND_PULLBACK", "D1_DONCHIAN55_200", "D1_TSMOM_60_200", "H4_COMPRESSION20_TREND"),
    "EURAUD": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_MEAN_REVERT_Z2_TO_SMA20"),
    "GBPAUD": ("D1_DONCHIAN55_200", "D1_TSMOM_60_200", "D1_TSMOM_120_200", "H4_DONCHIAN40_ADX20", "H4_PULLBACK_ADX20", "H4_MEAN_REVERT_Z2_TO_SMA20"),
}


def install_instrument(symbol: str) -> None:
    name = INSTRUMENT_NAMES[symbol]
    instrument = getattr(instruments, name, None)
    if instrument is None:
        raise RuntimeError(f"dukascopy-python missing instrument constant {name}")
    base.SYMBOLS[symbol] = instrument


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "D1_DONCHIAN55_200": base.d1_donchian55(symbol, h1),
        "D1_TSMOM_60_200": base.d1_tsmom(symbol, h1, 60),
        "D1_TSMOM_120_200": base.d1_tsmom(symbol, h1, 120),
        "H4_DONCHIAN40_ADX20": base.h4_donchian_adx(symbol, h1),
        "H4_PULLBACK_ADX20": base.h4_pullback_adx(symbol, h1),
        "H4_COMPRESSION20_TREND": base.h4_compression(symbol, h1),
        "H4_RSI2_TREND_PULLBACK": base.h4_rsi2_trend(symbol, h1),
        "H4_MEAN_REVERT_Z2_TO_SMA20": v2.h4_mean_to_sma(symbol, h1, 2.0, 20.0, "H4_MEAN_REVERT_Z2_TO_SMA20"),
        "H4_MEAN_REVERT_Z175_TO_SMA20": v2.h4_mean_to_sma(symbol, h1, 1.75, 18.0, "H4_MEAN_REVERT_Z175_TO_SMA20"),
    }
    return {name: frames[name] for name in PAIR_CANDIDATES[symbol]}


def assess(symbol: str, strategy: str, trades: pd.DataFrame) -> dict:
    base_cost, stress_cost, severe_cost = COSTS[symbol]
    stress = base.metrics(trades, symbol, stress_cost)
    eras = {}
    positive_eras = 0
    for name, start, end in base.ERAS:
        subset = trades[(trades["entry_time"] >= start) & (trades["entry_time"] < end)] if not trades.empty else trades
        m = base.metrics(subset, symbol, stress_cost)
        eras[name] = m
        if m["trades"] >= 5 and m["expectancy_r"] > 0 and m["profit_factor"] > 1.0:
            positive_eras += 1
    recent = eras["2024_2026"]
    ci_low = stress["bootstrap_ci_low"]
    strong = bool(
        stress["trades"] >= 40
        and stress["expectancy_r"] >= 0.05
        and stress["profit_factor"] >= 1.10
        and positive_eras >= 3
        and recent["trades"] >= 8
        and recent["expectancy_r"] > 0
        and recent["profit_factor"] > 1.0
        and ci_low is not None
        and ci_low > 0
    )
    watch = bool(
        not strong
        and stress["trades"] >= 30
        and stress["expectancy_r"] > 0
        and stress["profit_factor"] > 1.0
        and positive_eras >= 2
        and recent["trades"] >= 5
        and recent["expectancy_r"] > 0
        and recent["profit_factor"] > 1.0
    )
    return {
        "symbol": symbol,
        "strategy": strategy,
        "status": "STRONG_RESEARCH_PASS" if strong else ("WATCH" if watch else "REJECT"),
        "positive_eras": positive_eras,
        "base": base.metrics(trades, symbol, base_cost),
        "stress": stress,
        "severe": base.metrics(trades, symbol, severe_cost),
        "eras_stress": eras,
    }


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(SYMBOLS)}")
    install_instrument(symbol)
    print(f"FETCH {symbol} remaining-pair public Dukascopy BID H1")
    h1 = base.fetch_h1(symbol)
    print(f"COVERAGE rows={len(h1)} start={h1.time.min()} end={h1.time.max()}")
    frames = generate(symbol, h1)
    scorecard = [assess(symbol, name, trades) for name, trades in frames.items()]
    rank = {"STRONG_RESEARCH_PASS": 2, "WATCH": 1, "REJECT": 0}
    scorecard.sort(key=lambda r: (rank[r["status"]], r["stress"]["expectancy_r"], r["stress"]["profit_factor"]), reverse=True)
    champion = scorecard[0]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": symbol,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "data_start": str(base.DATA_START.date()),
        "data_end_exclusive": str(base.DATA_END.date()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "cost_model_pips": {"base": COSTS[symbol][0], "stress": COSTS[symbol][1], "severe": COSTS[symbol][2]},
        "selection_rule": "small frozen family set; no exhaustive parameter search; strong requires robust stress metrics, >=3 positive eras, positive recent era and positive moving-block bootstrap lower bound",
        "candidate_set": list(PAIR_CANDIDATES[symbol]),
        "coverage": {"h1_rows": int(len(h1)), "h1_start": str(h1.time.min()), "h1_end": str(h1.time.max())},
        "champion_by_rule": {"strategy": champion["strategy"], "status": champion["status"]},
        "scorecard": scorecard,
    }
    out = Path("research_output_remaining_fx_v1")
    out.mkdir(exist_ok=True)
    (out / f"remaining_fx_search_{symbol}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    for name, trades in frames.items():
        trades.to_csv(out / f"{symbol}_{name}_trades.csv", index=False)
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        s = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print("SCORE", json.dumps({
            "symbol": symbol,
            "strategy": row["strategy"],
            "status": row["status"],
            "trades": s["trades"],
            "expectancy_r": s["expectancy_r"],
            "pf": s["profit_factor"],
            "net_r": s["net_r"],
            "max_dd_r": s["max_dd_r"],
            "positive_eras": row["positive_eras"],
            "ci_low": s["bootstrap_ci_low"],
            "ci_high": s["bootstrap_ci_high"],
            "recent_exp": recent["expectancy_r"],
            "recent_pf": recent["profit_factor"],
        }, sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()

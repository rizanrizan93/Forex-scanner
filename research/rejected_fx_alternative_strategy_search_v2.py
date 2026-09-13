from __future__ import annotations

"""Second-stage, research-only search for FX pairs that failed the first tournament.

The family set is deliberately small and frozen before execution. It changes exit architecture
(long-horizon Chandelier trend exits) and adds one pair-agnostic H4 regime switch rather than
performing exhaustive parameter optimization.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2
import remaining_fx_pair_strategy_search_v1 as remaining

CONTRACT = "REJECTED_FX_ALTERNATIVE_STRATEGY_SEARCH_V2"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

SYMBOLS = (
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "EURGBP",
    "EURCHF",
    "EURAUD",
    "GBPAUD",
)

CANDIDATES = (
    "D1_TSMOM_252_CHANDELIER3",
    "D1_TSMOM_120_CHANDELIER3",
    "D1_DONCHIAN100_CHANDELIER3",
    "H4_DONCHIAN40_CHANDELIER3",
    "H4_MEAN_REVERT_Z2_TO_SMA20",
    "H4_ADAPTIVE_REGIME_V1",
)


def _adaptive_regime(symbol: str, h1: pd.DataFrame) -> pd.DataFrame:
    """Pair-agnostic regime switch: trend breakout at high ADX, mean reversion at low ADX."""
    x = v2.add_long_horizon(base.resample_ohlc(h1, "4h")).reset_index(drop=True)

    trend_long = (
        (x["adx14"] >= 25.0)
        & (x["ema50"] > x["ema200"])
        & (x["close"] > x["prior_high40"])
    )
    trend_short = (
        (x["adx14"] >= 25.0)
        & (x["ema50"] < x["ema200"])
        & (x["close"] < x["prior_low40"])
    )
    mean_long = (
        (x["adx14"] <= 15.0)
        & (x["z20"] <= -2.0)
        & (x["rsi14"] <= 30.0)
    )
    mean_short = (
        (x["adx14"] <= 15.0)
        & (x["z20"] >= 2.0)
        & (x["rsi14"] >= 70.0)
    )

    rows: list[dict] = []
    i = 0
    while i < len(x) - 1:
        mode: str | None = None
        direction = 0
        if bool(trend_long.iloc[i]):
            mode, direction = "TREND", 1
        elif bool(trend_short.iloc[i]):
            mode, direction = "TREND", -1
        elif bool(mean_long.iloc[i]):
            mode, direction = "MEAN", 1
        elif bool(mean_short.iloc[i]):
            mode, direction = "MEAN", -1
        if mode is None:
            i += 1
            continue

        atr0 = float(x.loc[i, "atr14"])
        if not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(x.loc[entry_i, "open"])
        risk = 1.5 * atr0
        stop = entry - direction * risk

        if mode == "TREND":
            last = min(len(x) - 1, entry_i + 60 - 1)
            highest = entry
            lowest = entry
            exit_i = last
            exit_px = float(x.loc[last, "close"])
            reason = "TREND_TIME"
            for j in range(entry_i, last + 1):
                open_, high, low, close = (
                    float(x.loc[j, key]) for key in ("open", "high", "low", "close")
                )
                if direction > 0:
                    if open_ <= stop:
                        exit_i, exit_px, reason = j, open_, "TREND_STOP_GAP"
                        break
                    if low <= stop:
                        exit_i, exit_px, reason = j, stop, "TREND_STOP"
                        break
                else:
                    if open_ >= stop:
                        exit_i, exit_px, reason = j, open_, "TREND_STOP_GAP"
                        break
                    if high >= stop:
                        exit_i, exit_px, reason = j, stop, "TREND_STOP"
                        break
                highest = max(highest, high)
                lowest = min(lowest, low)
                atr = float(x.loc[j, "atr14"])
                if math.isfinite(atr) and atr > 0:
                    candidate = highest - 3.0 * atr if direction > 0 else lowest + 3.0 * atr
                    stop = max(stop, candidate) if direction > 0 else min(stop, candidate)
                exit_px = close
        else:
            target = float(x.loc[i, "sma20"])
            if not math.isfinite(target) or (
                direction > 0 and target <= entry
            ) or (
                direction < 0 and target >= entry
            ):
                i += 1
                continue
            last = min(len(x) - 1, entry_i + 12 - 1)
            exit_i = last
            exit_px = float(x.loc[last, "close"])
            reason = "MEAN_TIME"
            for j in range(entry_i, last + 1):
                open_, high, low = (
                    float(x.loc[j, key]) for key in ("open", "high", "low")
                )
                if direction > 0:
                    if open_ <= stop:
                        exit_i, exit_px, reason = j, open_, "MEAN_STOP_GAP"
                        break
                    if open_ >= target:
                        exit_i, exit_px, reason = j, target, "MEAN_TARGET_GAP"
                        break
                    stop_hit, target_hit = low <= stop, high >= target
                else:
                    if open_ >= stop:
                        exit_i, exit_px, reason = j, open_, "MEAN_STOP_GAP"
                        break
                    if open_ <= target:
                        exit_i, exit_px, reason = j, target, "MEAN_TARGET_GAP"
                        break
                    stop_hit, target_hit = high >= stop, low <= target
                if stop_hit:  # conservative STOP_FIRST same-bar policy
                    exit_i, exit_px, reason = j, stop, "MEAN_STOP"
                    break
                if target_hit:
                    exit_i, exit_px, reason = j, target, "MEAN_TARGET"
                    break

        gross_r = direction * (exit_px - entry) / risk
        rows.append(
            base.trade_record(
                symbol,
                "H4_ADAPTIVE_REGIME_V1",
                x.loc[i, "time"],
                x.loc[entry_i, "time"],
                x.loc[exit_i, "time"],
                direction,
                entry,
                risk,
                gross_r,
                reason,
            )
        )
        i = exit_i + 1
    return pd.DataFrame(rows)


def generate(symbol: str, h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frames = {
        "D1_TSMOM_252_CHANDELIER3": v2.d1_tsmom_trailing(symbol, h1, 252),
        "D1_TSMOM_120_CHANDELIER3": v2.d1_tsmom_trailing(symbol, h1, 120),
        "D1_DONCHIAN100_CHANDELIER3": v2.d1_donchian_trailing(symbol, h1, 100),
        "H4_DONCHIAN40_CHANDELIER3": v2.h4_donchian_trailing(symbol, h1),
        "H4_MEAN_REVERT_Z2_TO_SMA20": v2.h4_mean_to_sma(
            symbol,
            h1,
            2.0,
            20.0,
            "H4_MEAN_REVERT_Z2_TO_SMA20",
        ),
        "H4_ADAPTIVE_REGIME_V1": _adaptive_regime(symbol, h1),
    }
    return {name: frames[name] for name in CANDIDATES}


def main() -> None:
    symbol = os.environ.get("CORE_SYMBOL", "").strip().upper()
    if symbol not in SYMBOLS:
        raise SystemExit(f"CORE_SYMBOL must be one of {list(SYMBOLS)}")

    remaining.install_instrument(symbol)
    print(f"FETCH {symbol} alternative-strategy public Dukascopy BID H1")
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
            "Frozen second-stage family set: long-horizon Chandelier exits plus one pair-agnostic "
            "H4 regime switch (ADX>=25 trend breakout; ADX<=15 Z2/RSI mean reversion)."
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

    out = Path("research_output_rejected_fx_v2")
    out.mkdir(exist_ok=True)
    (out / f"rejected_fx_alternative_{symbol}.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, trades in frames.items():
        trades.to_csv(out / f"{symbol}_{name}_trades.csv", index=False)

    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        stress = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print(
            "ALT_SCORE "
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

from __future__ import annotations

"""GBPAUD V5 component-divergence research.

GBPAUD is a cross rate. This frozen family therefore tests whether the cross has a more stable
edge when the GBPUSD and AUDUSD component legs disagree in trend/momentum, rather than adding
more parameter variants to previously rejected GBPAUD-only strategies.

Research-only: no execution influence and no promotion authority.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2
import remaining_fx_pair_strategy_search_v1 as remaining
import gbpaud_strategy_search_v4 as v4

CONTRACT = "GBPAUD_COMPONENT_STRATEGY_SEARCH_V5"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
SYMBOL = "GBPAUD"

CANDIDATES = (
    "D1_COMPONENT_EMA50_DIVERGENCE_CHANDELIER3",
    "D1_COMPONENT_EMA50_200_STRICT_CHANDELIER3",
    "D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3",
    "D1_COMPONENT_RET126_OPPOSITE_CHANDELIER3",
    "H4_COMPONENT_EMA50_200_STRICT_ADX18_RR2",
    "H4_COMPONENT_RET120_OPPOSITE_ADX18_RR2",
)


def _component_frame(h1: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = v2.add_long_horizon(base.resample_ohlc(h1, rule)).copy()
    x["ret63"] = x["close"] / x["close"].shift(63) - 1.0
    x["ret126"] = x["close"] / x["close"].shift(126) - 1.0
    x["ret120"] = x["close"] / x["close"].shift(120) - 1.0
    return x


def _aligned(g_cross: pd.DataFrame, g_gbp: pd.DataFrame, g_aud: pd.DataFrame) -> pd.DataFrame:
    gbp = g_gbp[["time", "close", "ema50", "ema200", "ret63", "ret126", "ret120"]].rename(
        columns={c: f"gbp_{c}" for c in ("close", "ema50", "ema200", "ret63", "ret126", "ret120")}
    )
    aud = g_aud[["time", "close", "ema50", "ema200", "ret63", "ret126", "ret120"]].rename(
        columns={c: f"aud_{c}" for c in ("close", "ema50", "ema200", "ret63", "ret126", "ret120")}
    )
    return g_cross.merge(gbp, on="time", how="inner").merge(aud, on="time", how="inner")


def _d1_frames(gbpaud_h1: pd.DataFrame, gbpusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> pd.DataFrame:
    return _aligned(
        _component_frame(gbpaud_h1, "1D"),
        _component_frame(gbpusd_h1, "1D"),
        _component_frame(audusd_h1, "1D"),
    )


def _h4_frames(gbpaud_h1: pd.DataFrame, gbpusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> pd.DataFrame:
    return _aligned(
        _component_frame(gbpaud_h1, "4h"),
        _component_frame(gbpusd_h1, "4h"),
        _component_frame(audusd_h1, "4h"),
    )


def _d1_ema50_divergence(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (
        (x["close"] > x["ema200"])
        & (x["gbp_close"] > x["gbp_ema50"])
        & (x["aud_close"] < x["aud_ema50"])
    )
    short_sig = (
        (x["close"] < x["ema200"])
        & (x["gbp_close"] < x["gbp_ema50"])
        & (x["aud_close"] > x["aud_ema50"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        SYMBOL,
        "D1_COMPONENT_EMA50_DIVERGENCE_CHANDELIER3",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=3.0,
        max_hold=120,
    )


def _d1_strict_trend(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (
        (x["close"] > x["ema200"])
        & (x["gbp_ema50"] > x["gbp_ema200"])
        & (x["aud_ema50"] < x["aud_ema200"])
    )
    short_sig = (
        (x["close"] < x["ema200"])
        & (x["gbp_ema50"] < x["gbp_ema200"])
        & (x["aud_ema50"] > x["aud_ema200"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        SYMBOL,
        "D1_COMPONENT_EMA50_200_STRICT_CHANDELIER3",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=3.0,
        max_hold=120,
    )


def _d1_opposite_momentum(x: pd.DataFrame, period: int) -> pd.DataFrame:
    gbp_ret = x[f"gbp_ret{period}"]
    aud_ret = x[f"aud_ret{period}"]
    long_sig = (x["close"] > x["ema200"]) & (gbp_ret > 0) & (aud_ret < 0)
    short_sig = (x["close"] < x["ema200"]) & (gbp_ret < 0) & (aud_ret > 0)
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(
        SYMBOL,
        f"D1_COMPONENT_RET{period}_OPPOSITE_CHANDELIER3",
        x,
        direction,
        initial_stop_atr=2.0,
        trail_atr=3.0,
        max_hold=120,
    )


def _h4_strict_trend(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (
        (x["close"] > x["ema200"])
        & (x["adx14"] >= 18.0)
        & (x["gbp_ema50"] > x["gbp_ema200"])
        & (x["aud_ema50"] < x["aud_ema200"])
    )
    short_sig = (
        (x["close"] < x["ema200"])
        & (x["adx14"] >= 18.0)
        & (x["gbp_ema50"] < x["gbp_ema200"])
        & (x["aud_ema50"] > x["aud_ema200"])
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v4._simulate_fixed_rr(
        SYMBOL,
        "H4_COMPONENT_EMA50_200_STRICT_ADX18_RR2",
        x,
        direction,
        stop_atr=1.5,
        target_r=2.0,
        max_hold=30,
    )


def _h4_opposite_momentum(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (
        (x["close"] > x["ema200"])
        & (x["adx14"] >= 18.0)
        & (x["gbp_ret120"] > 0)
        & (x["aud_ret120"] < 0)
    )
    short_sig = (
        (x["close"] < x["ema200"])
        & (x["adx14"] >= 18.0)
        & (x["gbp_ret120"] < 0)
        & (x["aud_ret120"] > 0)
    )
    direction = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v4._simulate_fixed_rr(
        SYMBOL,
        "H4_COMPONENT_RET120_OPPOSITE_ADX18_RR2",
        x,
        direction,
        stop_atr=1.5,
        target_r=2.0,
        max_hold=30,
    )


def generate(gbpaud_h1: pd.DataFrame, gbpusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d1 = _d1_frames(gbpaud_h1, gbpusd_h1, audusd_h1)
    h4 = _h4_frames(gbpaud_h1, gbpusd_h1, audusd_h1)
    frames = {
        "D1_COMPONENT_EMA50_DIVERGENCE_CHANDELIER3": _d1_ema50_divergence(d1),
        "D1_COMPONENT_EMA50_200_STRICT_CHANDELIER3": _d1_strict_trend(d1),
        "D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3": _d1_opposite_momentum(d1, 63),
        "D1_COMPONENT_RET126_OPPOSITE_CHANDELIER3": _d1_opposite_momentum(d1, 126),
        "H4_COMPONENT_EMA50_200_STRICT_ADX18_RR2": _h4_strict_trend(h4),
        "H4_COMPONENT_RET120_OPPOSITE_ADX18_RR2": _h4_opposite_momentum(h4),
    }
    return {name: frames[name] for name in CANDIDATES}


def main() -> None:
    remaining.install_instrument(SYMBOL)
    print("FETCH GBPAUD/GBPUSD/AUDUSD V5 public Dukascopy BID H1")
    gbpaud_h1 = base.fetch_h1("GBPAUD")
    gbpusd_h1 = base.fetch_h1("GBPUSD")
    audusd_h1 = base.fetch_h1("AUDUSD")
    print(
        "COVERAGE "
        f"GBPAUD={len(gbpaud_h1)} GBPUSD={len(gbpusd_h1)} AUDUSD={len(audusd_h1)} "
        f"start={gbpaud_h1.time.min()} end={gbpaud_h1.time.max()}"
    )

    frames = generate(gbpaud_h1, gbpusd_h1, audusd_h1)
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
        "component_sources": ["GBPAUD", "GBPUSD", "AUDUSD"],
        "data_start": str(base.DATA_START.date()),
        "data_end_exclusive": str(base.DATA_END.date()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "cost_model_pips": {"base": base_cost, "stress": stress_cost, "severe": severe_cost},
        "research_change": (
            "Frozen V5 family shift to component-leg confirmation: GBPAUD entries require GBPUSD/AUDUSD "
            "trend or momentum divergence. No candidate parameters are changed after seeing results."
        ),
        "candidate_set": list(CANDIDATES),
        "coverage": {
            "gbpaud_h1_rows": int(len(gbpaud_h1)),
            "gbpusd_h1_rows": int(len(gbpusd_h1)),
            "audusd_h1_rows": int(len(audusd_h1)),
            "start": str(gbpaud_h1.time.min()),
            "end": str(gbpaud_h1.time.max()),
        },
        "champion_by_rule": {"strategy": champion["strategy"], "status": champion["status"]},
        "scorecard": scorecard,
    }

    out = Path("research_output_gbpaud_v5")
    out.mkdir(exist_ok=True)
    (out / "gbpaud_component_strategy_search_v5.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    for name, trades in frames.items():
        trades.to_csv(out / f"GBPAUD_{name}_trades.csv", index=False)

    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        stress = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print(
            "V5_SCORE "
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

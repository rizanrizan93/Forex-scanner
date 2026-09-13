from __future__ import annotations

"""EURAUD V4 component-divergence search, research-only.

The family mirrors the cross-rate component test used for GBPAUD, but is frozen for EURAUD
before results: EURAUD entries are conditioned on disagreement between EURUSD and AUDUSD.
No order path, execution influence, or promotion authority is present.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import four_pair_strategy_search_v1 as base
import four_pair_strategy_search_v2 as v2
import remaining_fx_pair_strategy_search_v1 as remaining

CONTRACT = "EURAUD_COMPONENT_STRATEGY_SEARCH_V4"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
SYMBOL = "EURAUD"

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


def _aligned(cross: pd.DataFrame, eur: pd.DataFrame, aud: pd.DataFrame) -> pd.DataFrame:
    eur = eur[["time", "close", "ema50", "ema200", "ret63", "ret126", "ret120"]].rename(
        columns={c: f"eur_{c}" for c in ("close", "ema50", "ema200", "ret63", "ret126", "ret120")}
    )
    aud = aud[["time", "close", "ema50", "ema200", "ret63", "ret126", "ret120"]].rename(
        columns={c: f"aud_{c}" for c in ("close", "ema50", "ema200", "ret63", "ret126", "ret120")}
    )
    return cross.merge(eur, on="time", how="inner").merge(aud, on="time", how="inner")


def _simulate_fixed_rr(
    strategy: str,
    x: pd.DataFrame,
    direction: pd.Series,
    *,
    stop_atr: float = 1.5,
    target_r: float = 2.0,
    max_hold: int = 30,
) -> pd.DataFrame:
    f = x.reset_index(drop=True)
    dirs = direction.fillna(0).astype(int).to_numpy()
    rows = []
    i = 0
    while i < len(f) - 1:
        d = int(dirs[i])
        if d == 0:
            i += 1
            continue
        atr0 = float(f.loc[i, "atr14"])
        if not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue
        ei = i + 1
        entry = float(f.loc[ei, "open"])
        risk = stop_atr * atr0
        stop = entry - d * risk
        target = entry + d * target_r * risk
        last = min(len(f) - 1, ei + max_hold - 1)
        xi = last
        exit_px = float(f.loc[last, "close"])
        reason = "TIME"
        for j in range(ei, last + 1):
            o, hi, lo = (float(f.loc[j, k]) for k in ("open", "high", "low"))
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
        rows.append(
            base.trade_record(
                SYMBOL,
                strategy,
                f.loc[i, "time"],
                f.loc[ei, "time"],
                f.loc[xi, "time"],
                d,
                entry,
                risk,
                gross,
                reason,
            )
        )
        i = xi + 1
    return pd.DataFrame(rows)


def _d1_frames(euraud_h1: pd.DataFrame, eurusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> pd.DataFrame:
    return _aligned(
        _component_frame(euraud_h1, "1D"),
        _component_frame(eurusd_h1, "1D"),
        _component_frame(audusd_h1, "1D"),
    )


def _h4_frames(euraud_h1: pd.DataFrame, eurusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> pd.DataFrame:
    return _aligned(
        _component_frame(euraud_h1, "4h"),
        _component_frame(eurusd_h1, "4h"),
        _component_frame(audusd_h1, "4h"),
    )


def _d1_ema50_divergence(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (x["close"] > x["ema200"]) & (x["eur_close"] > x["eur_ema50"]) & (x["aud_close"] < x["aud_ema50"])
    short_sig = (x["close"] < x["ema200"]) & (x["eur_close"] < x["eur_ema50"]) & (x["aud_close"] > x["aud_ema50"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(SYMBOL, "D1_COMPONENT_EMA50_DIVERGENCE_CHANDELIER3", x, d, 2.0, 3.0, 120)


def _d1_strict(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (x["close"] > x["ema200"]) & (x["eur_ema50"] > x["eur_ema200"]) & (x["aud_ema50"] < x["aud_ema200"])
    short_sig = (x["close"] < x["ema200"]) & (x["eur_ema50"] < x["eur_ema200"]) & (x["aud_ema50"] > x["aud_ema200"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(SYMBOL, "D1_COMPONENT_EMA50_200_STRICT_CHANDELIER3", x, d, 2.0, 3.0, 120)


def _d1_ret(x: pd.DataFrame, period: int) -> pd.DataFrame:
    eur_ret = x[f"eur_ret{period}"]
    aud_ret = x[f"aud_ret{period}"]
    long_sig = (x["close"] > x["ema200"]) & (eur_ret > 0) & (aud_ret < 0)
    short_sig = (x["close"] < x["ema200"]) & (eur_ret < 0) & (aud_ret > 0)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return v2.simulate_chandelier(SYMBOL, f"D1_COMPONENT_RET{period}_OPPOSITE_CHANDELIER3", x, d, 2.0, 3.0, 120)


def _h4_strict(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (x["close"] > x["ema200"]) & (x["adx14"] >= 18.0) & (x["eur_ema50"] > x["eur_ema200"]) & (x["aud_ema50"] < x["aud_ema200"])
    short_sig = (x["close"] < x["ema200"]) & (x["adx14"] >= 18.0) & (x["eur_ema50"] < x["eur_ema200"]) & (x["aud_ema50"] > x["aud_ema200"])
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr("H4_COMPONENT_EMA50_200_STRICT_ADX18_RR2", x, d)


def _h4_ret(x: pd.DataFrame) -> pd.DataFrame:
    long_sig = (x["close"] > x["ema200"]) & (x["adx14"] >= 18.0) & (x["eur_ret120"] > 0) & (x["aud_ret120"] < 0)
    short_sig = (x["close"] < x["ema200"]) & (x["adx14"] >= 18.0) & (x["eur_ret120"] < 0) & (x["aud_ret120"] > 0)
    d = pd.Series(np.where(long_sig, 1, np.where(short_sig, -1, 0)), index=x.index)
    return _simulate_fixed_rr("H4_COMPONENT_RET120_OPPOSITE_ADX18_RR2", x, d)


def generate(euraud_h1: pd.DataFrame, eurusd_h1: pd.DataFrame, audusd_h1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d1 = _d1_frames(euraud_h1, eurusd_h1, audusd_h1)
    h4 = _h4_frames(euraud_h1, eurusd_h1, audusd_h1)
    frames = {
        "D1_COMPONENT_EMA50_DIVERGENCE_CHANDELIER3": _d1_ema50_divergence(d1),
        "D1_COMPONENT_EMA50_200_STRICT_CHANDELIER3": _d1_strict(d1),
        "D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3": _d1_ret(d1, 63),
        "D1_COMPONENT_RET126_OPPOSITE_CHANDELIER3": _d1_ret(d1, 126),
        "H4_COMPONENT_EMA50_200_STRICT_ADX18_RR2": _h4_strict(h4),
        "H4_COMPONENT_RET120_OPPOSITE_ADX18_RR2": _h4_ret(h4),
    }
    return {name: frames[name] for name in CANDIDATES}


def main() -> None:
    remaining.install_instrument(SYMBOL)
    print("FETCH EURAUD/EURUSD/AUDUSD V4 public Dukascopy BID H1")
    euraud = base.fetch_h1("EURAUD")
    eurusd = base.fetch_h1("EURUSD")
    audusd = base.fetch_h1("AUDUSD")
    print(f"COVERAGE EURAUD={len(euraud)} EURUSD={len(eurusd)} AUDUSD={len(audusd)} start={euraud.time.min()} end={euraud.time.max()}")
    frames = generate(euraud, eurusd, audusd)
    scorecard = [remaining.assess(SYMBOL, name, trades) for name, trades in frames.items()]
    rank = {"STRONG_RESEARCH_PASS": 2, "WATCH": 1, "REJECT": 0}
    scorecard.sort(key=lambda r: (rank[r["status"]], r["stress"]["expectancy_r"], r["stress"]["profit_factor"]), reverse=True)
    champion = scorecard[0]
    base_cost, stress_cost, severe_cost = remaining.COSTS[SYMBOL]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "symbol": SYMBOL,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python 4.0.1",
        "component_sources": ["EURAUD", "EURUSD", "AUDUSD"],
        "data_start": str(base.DATA_START.date()),
        "data_end_exclusive": str(base.DATA_END.date()),
        "same_bar_policy": base.SAME_BAR_POLICY,
        "cost_model_pips": {"base": base_cost, "stress": stress_cost, "severe": severe_cost},
        "research_change": "Frozen component-leg family: EURAUD signals require EURUSD/AUDUSD trend or momentum divergence. Same family used cross-pair, no post-result retuning.",
        "candidate_set": list(CANDIDATES),
        "coverage": {"euraud_h1_rows": len(euraud), "eurusd_h1_rows": len(eurusd), "audusd_h1_rows": len(audusd), "start": str(euraud.time.min()), "end": str(euraud.time.max())},
        "champion_by_rule": {"strategy": champion["strategy"], "status": champion["status"]},
        "scorecard": scorecard,
    }
    out = Path("research_output_euraud_component_v4")
    out.mkdir(exist_ok=True)
    (out / "euraud_component_strategy_v4.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    for name, trades in frames.items():
        trades.to_csv(out / f"EURAUD_{name}_trades.csv", index=False)
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True, default=str))
    for row in scorecard:
        s = row["stress"]
        recent = row["eras_stress"]["2024_2026"]
        print("EURAUD_V4_SCORE " + json.dumps({"strategy": row["strategy"], "status": row["status"], "trades": s["trades"], "expectancy_r": s["expectancy_r"], "pf": s["profit_factor"], "net_r": s["net_r"], "max_dd_r": s["max_dd_r"], "positive_eras": row["positive_eras"], "ci_low": s["bootstrap_ci_low"], "ci_high": s["bootstrap_ci_high"], "recent_exp": recent["expectancy_r"], "recent_pf": recent["profit_factor"]}, sort_keys=True))
    print("Research only: execution_influence=false promotion_authority=false")


if __name__ == "__main__":
    main()

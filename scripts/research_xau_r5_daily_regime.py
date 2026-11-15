"""Out-of-model R5 falsification: is Asian trend alpha conditional on DAILY regime?

Hypotheses defined before reading these results:
(1) LONG-only, (2) last completed D1 EMA20/100 direction concordance,
(3) long-only with completed-day 60D breakout / new-high trend condition.
Data publisher mid OHLC, NO broker-native validation. NO LIVE integration.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from dataclasses import replace

from fx_scanner.xau_microalpha_r4 import R4Settings, backtest
from fx_scanner.xau_microalpha_r5 import features, build_signals
from research_xau_microalpha_r3_multiyear import load_history
from research_xau_microalpha_r3_lagged_macro import load_lagged_macro

OUT = Path("rizan_xau_r5_daily_regime_diagnostic.json")
SPLITS = {
    "2019_2022": ("2019-01-01", "2023-01-01"),
    "2023_2024": ("2023-01-01", "2025-01-01"),
    "2025_JAN2026": ("2025-01-01", "2026-01-10"),
}


def completed_daily_features(f: pd.DataFrame) -> pd.DataFrame:
    daily = f.set_index("datetime").resample("1D", label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), count=("close", "size"),
    )
    # 23h trading days may have 276 M5 bars; incomplete holidays/Sundays excluded.
    daily = daily.loc[daily["count"].ge(240)].copy()
    daily["d1_ema20"] = daily["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    daily["d1_ema100"] = daily["close"].ewm(span=100, adjust=False, min_periods=100).mean()
    daily["d1_ema20_prev5"] = daily["d1_ema20"].shift(5)
    daily["d1_high_prev60"] = daily["high"].rolling(60, min_periods=60).max().shift(1)
    daily["available_at"] = daily.index + pd.Timedelta(days=1)
    return daily.reset_index(drop=True)


def run():
    raw, integrity = load_history()
    f = features(raw)
    s = build_signals(f, candidate="ASIA_OPEN_BREAKOUT")
    d1 = completed_daily_features(s)
    q = pd.merge_asof(
        s[["closed_at"]], d1.sort_values("available_at"),
        left_on="closed_at", right_on="available_at", direction="backward",
        tolerance=pd.Timedelta(days=5),
    )
    d1up = q["close"].gt(q["d1_ema20"]) & q["d1_ema20"].gt(q["d1_ema100"]) & q["d1_ema20"].gt(q["d1_ema20_prev5"])
    d1down = q["close"].lt(q["d1_ema20"]) & q["d1_ema20"].lt(q["d1_ema100"]) & q["d1_ema20"].lt(q["d1_ema20_prev5"])
    breakout60 = q["close"].gt(q["d1_high_prev60"]) & q["close"].gt(q["d1_ema100"])
    # Publisher-lagged daily US rates and broad USD proxies, as-of only.
    # These have NOT been independently audited against actual release timestamps.
    macro = load_lagged_macro()
    f_macro = pd.merge_asof(
        s[["closed_at"]].sort_values("closed_at"),
        macro.sort_values("asof"), left_on="closed_at", right_on="asof",
        direction="backward", tolerance=pd.Timedelta(hours=2),
    )
    lower_real = pd.to_numeric(f_macro["macro_DFII10_chg7d"], errors="coerce").lt(0)
    weaker_usd = pd.to_numeric(f_macro["macro_DTWEXBGS_pct7d"], errors="coerce").lt(0)
    higher_real = pd.to_numeric(f_macro["macro_DFII10_chg7d"], errors="coerce").gt(0)
    stronger_usd = pd.to_numeric(f_macro["macro_DTWEXBGS_pct7d"], errors="coerce").gt(0)
    # Daily as-of is backward: no today's unclosed 24h candle is exposed.
    masks = {
        "BASELINE_ASIA_OPEN_BREAKOUT": s["r4_signal"].ne(0),
        "LONG_ONLY": s["r4_signal"].eq(1),
        "D1_EMA20_100_CONCORDANT": (s["r4_signal"].eq(1) & d1up) | (s["r4_signal"].eq(-1) & d1down),
        "LONG_ONLY_D1_60DAY_BREAK": s["r4_signal"].eq(1) & breakout60,
        "LONG_D1_60DAY_AND_REAL_DOWN": s["r4_signal"].eq(1) & breakout60 & lower_real,
        "LONG_D1_60DAY_AND_REAL_USD_DOWN": (
            s["r4_signal"].eq(1) & breakout60 & lower_real & weaker_usd),
        "D1_TREND_REAL_USD_CONCORDANCE": (
            (s["r4_signal"].eq(1) & d1up & lower_real & weaker_usd)
            | (s["r4_signal"].eq(-1) & d1down & higher_real & stronger_usd)),
    }
    cfg = R4Settings()
    report = {
        "contract": "RIZAN_R5_DAILY_REGIME_FALSIFICATION_READONLY",
        "price_manifest": integrity, "d1_rows": len(d1), "macro_proxy_h1_rows": len(macro),
        "publication": "Completed UTC calendar D1 available only from next UTC midnight",
        "out_of_sample_claim": False, "selection_bias": "Exploratory after observing R5 failures",
        "cost_model": "FP broker data NOT validated, constant roundtrip friction 0.80 USD/oz",
        "variants": {},
    }
    for name, eligible in masks.items():
        tmp = s.copy()
        tmp["r4_signal"] = tmp["r4_signal"].where(eligible.fillna(False), 0)
        tmp["r4_structural_stop"] = tmp["r4_structural_stop"].where(eligible.fillna(False))
        full, _ = backtest(tmp, cfg, session="ASIA")
        intervals = {
            k: backtest(tmp, cfg, session="ASIA", window_start=lo, window_end=hi)[0]
            for k, (lo, hi) in SPLITS.items()
        }
        report["variants"][name] = {
            "full": full, "panel_restarts": intervals,
            "raw_signals": int(tmp["r4_signal"].ne(0).sum()),
        }
        print(
            f"R5_D1 {name} ending={full['ending_usd']} PF={full['profit_factor']} "
            f"dd={full['closed_dd_pct']} count={full['count']}", flush=True
        )
        OUT.write_text(json.dumps(report, indent=2, default=str))
    # Post-selection falsification of the only exploratory positive case.
    # iid trade bootstrap is NOT a valid de-overfitted OOS confidence interval.
    selected = s.copy()
    gate = masks["LONG_D1_60DAY_AND_REAL_DOWN"].fillna(False)
    selected["r4_signal"] = selected["r4_signal"].where(gate, 0)
    selected["r4_structural_stop"] = selected["r4_structural_stop"].where(gate)
    stress = {}
    for fee in (.4, .8, 1.2, 1.6, 2.4):
        cfg_fee = replace(cfg, roundtrip_cost_usd_per_oz=fee)
        x, _ = backtest(selected, cfg_fee, session="ASIA")
        stress[str(fee)] = x
        print(
            f"R5_POSITIVE_COST fee={fee} ending={x['ending_usd']} "
            f"trades={x['count']} PF={x['profit_factor']}", flush=True
        )
    ref, trades = backtest(selected, cfg, session="ASIA")
    if trades.empty:
        raise ValueError("CANNOT_BOOTSTRAP_WITHOUT_TRADES")
    r_values = (trades["pnl_usd"] / trades["risk_usd"]).to_numpy()
    if not np.isfinite(r_values).all():
        raise ValueError("BOOTSTRAP_R_VALUES_INVALID")
    rng = np.random.default_rng(20261116)
    sample_mean = rng.choice(r_values, size=(5000, len(r_values)), replace=True).mean(axis=1)
    boot = {
        "trades": len(trades),
        "observed_mean_r": round(float(r_values.mean()), 4),
        "mean_r_iid_bootstrap_95pct": [
            round(float(np.quantile(sample_mean, .025)), 4),
            round(float(np.quantile(sample_mean, .975)), 4),
        ],
        "fraction_bootstrap_positive_mean_r": round(float((sample_mean > 0).mean()), 4),
        "warning": (
            "Post-hoc model selection + IID trade resampling. Serial correlation, "
            "regime-shifts and multiple-hypothesis penalties are not corrected."
        ),
    }
    report["positive_gate_cost_stress"] = stress
    report["positive_gate_uncertainty"] = boot
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("R5_POSITIVE_GATE_BOOTSTRAP " + json.dumps(boot), flush=True)
    print("R5_DAILY_DIAGNOSTIC_COMPLETE", flush=True)
    return report


if __name__ == "__main__":
    run()

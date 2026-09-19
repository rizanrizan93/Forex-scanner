from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import five_core_tournament_v1 as base
import xau_d1_staggered_v14 as v14

CONTRACT = "XAU_D1_C2R1_CONFIRM_V15"
EXECUTION_INFLUENCE = False
VARIANT = v14.Variant(cadence_days=2, target_r=1.0)
SEED = 20260919
BLOCK_SIZE = 5
BOOTSTRAP_TRIALS = 5000


def _block_bootstrap_ci(values: np.ndarray) -> dict:
    if len(values) < BLOCK_SIZE:
        return {"trials": 0, "block_size": BLOCK_SIZE, "mean_ci95": [None, None], "positive_fraction": None}
    rng = np.random.default_rng(SEED)
    means = np.empty(BOOTSTRAP_TRIALS, dtype=float)
    n = len(values)
    for i in range(BOOTSTRAP_TRIALS):
        sample = []
        while len(sample) < n:
            start = int(rng.integers(0, max(1, n - BLOCK_SIZE + 1)))
            sample.extend(values[start:start + BLOCK_SIZE].tolist())
        means[i] = float(np.mean(sample[:n]))
    return {
        "trials": BOOTSTRAP_TRIALS,
        "block_size": BLOCK_SIZE,
        "mean_ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
        "positive_fraction": float((means > 0).mean()),
    }


def _annual_metrics(df: pd.DataFrame, *, cost_abs: float) -> dict:
    if df.empty:
        return {}
    x = v14._repriced(df, cost_abs=cost_abs).copy()
    x["year"] = pd.DatetimeIndex(x["entry_time"]).year
    out = {}
    for year, group in x.groupby("year"):
        out[str(int(year))] = v14._metrics(group, cost_abs=cost_abs)
    return out


def build_report(h1: pd.DataFrame) -> dict:
    d1 = v14._daily_frame(h1)
    all_trades = v14.simulate_staggered(d1, variant=VARIANT)

    dev = v14._period(all_trades, v14.DEV_START, v14.VALIDATION_START)
    validation = v14._period(all_trades, v14.VALIDATION_START, v14.OOS_START)
    oos = v14._period(all_trades, v14.OOS_START, v14.END_EXCLUSIVE)

    dev_stress = v14._metrics(dev, cost_abs=v14.STRESS_COST_USD)
    validation_stress = v14._metrics(validation, cost_abs=v14.STRESS_COST_USD)
    oos_base = v14._metrics(oos, cost_abs=v14.BASE_COST_USD)
    oos_stress = v14._metrics(oos, cost_abs=v14.STRESS_COST_USD)
    repriced_oos = v14._repriced(oos, cost_abs=v14.STRESS_COST_USD).sort_values("entry_time")
    bootstrap = _block_bootstrap_ci(repriced_oos["net_r"].to_numpy(float))

    active_regime = d1[
        (d1["time"] >= v14.OOS_START)
        & (d1["time"] < v14.END_EXCLUSIVE)
        & (d1["direction"] != 0)
    ]
    oos_entry_days = len(set(pd.DatetimeIndex(oos["entry_time"]).date)) if not oos.empty else 0
    coverage_active_regime = (
        oos_entry_days / len(active_regime)
        if len(active_regime)
        else 0.0
    )

    gate_pass = bool(
        v14._gate(dev_stress, v14.DEV_GATE)
        and v14._gate(validation_stress, v14.VALIDATION_GATE)
        and v14._oos_gate(oos_stress)
        and bootstrap["mean_ci95"][0] is not None
        and float(bootstrap["mean_ci95"][0]) > 0.0
        and float(bootstrap["positive_fraction"]) >= 0.95
    )

    return {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "symbol": v14.SYMBOL,
        "variant": {
            "variant_id": VARIANT.variant_id,
            "cadence_days": VARIANT.cadence_days,
            "target_r": VARIANT.target_r,
            "max_active": VARIANT.max_active,
            "stop_atr": v14.STOP_ATR,
            "max_hold_days": v14.MAX_HOLD_DAYS,
        },
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python",
        "history": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
        },
        "selection_provenance": {
            "source": "V14 development + validation only",
            "oos_seen_before_v15": False,
            "reason": (
                "C2/R1 was frozen because it combines substantially higher frequency with "
                "positive DEV/VALIDATION stressed expectancy and validation win rate above 55%."
            ),
        },
        "development_stressed": dev_stress,
        "validation_stressed": validation_stress,
        "locked_oos": {
            "period": "2025-01-01..2026-08-31",
            "base": oos_base,
            "stressed": oos_stress,
            "annual_stressed": _annual_metrics(oos, cost_abs=v14.STRESS_COST_USD),
            "block_bootstrap": bootstrap,
            "concurrency": v14._concurrency(oos),
            "active_regime_days": int(len(active_regime)),
            "entry_days": int(oos_entry_days),
            "entry_coverage_of_active_regime_days": float(coverage_active_regime),
        },
        "final_gate": {
            **v14.OOS_GATE,
            "bootstrap_ci_low_gt_zero": True,
            "bootstrap_positive_fraction_min": 0.95,
        },
        "promotion_eligible": gate_pass,
        "risk_note": (
            "Overlapping D1 tranches are correlated. Research R is per tranche and is not "
            "a recommended account-risk percentage. Any DEMO implementation must size "
            "aggregate open risk under the existing account-wide guards."
        ),
    }


def main() -> None:
    base.SYMBOLS = {v14.SYMBOL: base.SYMBOLS[v14.SYMBOL]}
    base.SLOW_START = pd.Timestamp("2012-01-01").to_pydatetime()
    print("FETCH XAUUSD H1 2012-2026")
    h1 = base.fetch_h1(v14.SYMBOL)
    report = build_report(h1)
    out = Path("research_output_xau_d1_c2r1_confirm_v15")
    out.mkdir(exist_ok=True)
    p = out / "xau_d1_c2r1_confirm_v15.json"
    p.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    oos = report["locked_oos"]["stressed"]
    print(
        "XAU_D1_C2R1_CONFIRM_V15 "
        f"trades={oos['trades']} win={oos['win_rate']} pf={oos['profit_factor']} "
        f"exp={oos['expectancy_r']} dd={oos['max_realized_drawdown_r']} "
        f"coverage_active={report['locked_oos']['entry_coverage_of_active_regime_days']} "
        f"promotion_eligible={int(bool(report['promotion_eligible']))}"
    )
    print("V15_BOOTSTRAP", json.dumps(report["locked_oos"]["block_bootstrap"], sort_keys=True))
    print("Research only: execution_influence=false")


if __name__ == "__main__":
    main()

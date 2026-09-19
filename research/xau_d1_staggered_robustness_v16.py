from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

import five_core_tournament_v1 as base
import xau_d1_staggered_v14 as v14

CONTRACT = "XAU_D1_STAGGERED_ROBUSTNESS_V16"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True
SEED = 20260919
BLOCK_SIZE = 5
BOOTSTRAP_TRIALS = 2000

CURRENT_YEAR_GATE = {
    "trades_min": 30,
    "expectancy_r_min": 0.05,
    "profit_factor_min": 1.10,
}
AGGREGATE_GATE = {
    "trades_min": 100,
    "expectancy_r_min": 0.15,
    "profit_factor_min": 1.30,
}


def _period_metrics(df: pd.DataFrame, *, cost_abs: float) -> dict:
    return v14._metrics(df, cost_abs=cost_abs)


def _subperiod(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return v14._period(
        df,
        pd.Timestamp(start, tz="UTC"),
        pd.Timestamp(end, tz="UTC"),
    )


def _direction_metrics(df: pd.DataFrame, *, cost_abs: float) -> dict:
    if df.empty:
        return {"LONG": _period_metrics(df, cost_abs=cost_abs), "SHORT": _period_metrics(df, cost_abs=cost_abs)}
    return {
        "LONG": _period_metrics(df[df["direction"] > 0], cost_abs=cost_abs),
        "SHORT": _period_metrics(df[df["direction"] < 0], cost_abs=cost_abs),
    }


def _quarterly_metrics(df: pd.DataFrame, *, cost_abs: float) -> dict:
    windows = (
        ("2025Q1", "2025-01-01", "2025-04-01"),
        ("2025Q2", "2025-04-01", "2025-07-01"),
        ("2025Q3", "2025-07-01", "2025-10-01"),
        ("2025Q4", "2025-10-01", "2026-01-01"),
        ("2026Q1", "2026-01-01", "2026-04-01"),
        ("2026Q2", "2026-04-01", "2026-07-01"),
        ("2026Q3_partial", "2026-07-01", "2026-09-01"),
    )
    return {
        label: _period_metrics(_subperiod(df, start, end), cost_abs=cost_abs)
        for label, start, end in windows
    }


def _bootstrap(values: np.ndarray) -> dict:
    if len(values) < BLOCK_SIZE:
        return {
            "trials": 0,
            "block_size": BLOCK_SIZE,
            "mean_ci95": [None, None],
            "positive_fraction": None,
        }
    rng = np.random.default_rng(SEED)
    n = len(values)
    means = np.empty(BOOTSTRAP_TRIALS, dtype=float)
    for i in range(BOOTSTRAP_TRIALS):
        sample: list[float] = []
        while len(sample) < n:
            start = int(rng.integers(0, max(1, n - BLOCK_SIZE + 1)))
            sample.extend(values[start:start + BLOCK_SIZE].tolist())
        means[i] = float(np.mean(sample[:n]))
    return {
        "trials": BOOTSTRAP_TRIALS,
        "block_size": BLOCK_SIZE,
        "mean_ci95": [
            float(np.quantile(means, 0.025)),
            float(np.quantile(means, 0.975)),
        ],
        "positive_fraction": float((means > 0).mean()),
    }


def _passes(metrics: dict, gate: dict) -> bool:
    return bool(
        metrics["trades"] >= int(gate["trades_min"])
        and metrics["expectancy_r"] is not None
        and metrics["expectancy_r"] >= float(gate["expectancy_r_min"])
        and metrics["profit_factor"] is not None
        and metrics["profit_factor"] >= float(gate["profit_factor_min"])
    )


def _positive(metrics: dict) -> bool:
    return bool(
        metrics["trades"] > 0
        and metrics["expectancy_r"] is not None
        and metrics["expectancy_r"] > 0.0
        and metrics["profit_factor"] is not None
        and metrics["profit_factor"] > 1.0
    )


def _entry_frequency(df: pd.DataFrame, start: str, end: str) -> dict:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    days = int((end_ts - start_ts).days)
    entry_days = len(set(pd.DatetimeIndex(df["entry_time"]).date)) if not df.empty else 0
    trades = int(len(df))
    return {
        "calendar_days": days,
        "trades": trades,
        "entry_days": int(entry_days),
        "trades_per_calendar_day": float(trades / days) if days else 0.0,
        "trades_per_entry_day": float(trades / entry_days) if entry_days else 0.0,
    }


def build_report(h1: pd.DataFrame) -> dict:
    d1 = v14._daily_frame(h1)
    rows: list[dict] = []

    for variant in v14.VARIANTS:
        trades = v14.simulate_staggered(d1, variant=variant)
        oos = v14._period(trades, v14.OOS_START, v14.END_EXCLUSIVE)
        y2025 = _subperiod(oos, "2025-01-01", "2026-01-01")
        y2026 = _subperiod(oos, "2026-01-01", "2026-09-01")

        aggregate = _period_metrics(oos, cost_abs=v14.STRESS_COST_USD)
        m2025 = _period_metrics(y2025, cost_abs=v14.STRESS_COST_USD)
        m2026 = _period_metrics(y2026, cost_abs=v14.STRESS_COST_USD)
        repriced = v14._repriced(oos, cost_abs=v14.STRESS_COST_USD).sort_values(["entry_time", "exit_time"])
        bootstrap = _bootstrap(repriced["net_r"].to_numpy(float))

        aggregate_pass = _passes(aggregate, AGGREGATE_GATE)
        current_year_pass = _passes(m2026, CURRENT_YEAR_GATE)
        both_years_positive = _positive(m2025) and _positive(m2026)
        bootstrap_positive = bool(
            bootstrap["mean_ci95"][0] is not None
            and float(bootstrap["mean_ci95"][0]) > 0.0
            and float(bootstrap["positive_fraction"]) >= 0.95
        )

        exp2025 = float(m2025["expectancy_r"] or -999.0)
        exp2026 = float(m2026["expectancy_r"] or -999.0)
        pf2025 = float(m2025["profit_factor"] or 0.0)
        pf2026 = float(m2026["profit_factor"] or 0.0)
        robustness_key = (
            int(both_years_positive),
            int(current_year_pass),
            min(exp2025, exp2026),
            min(pf2025, pf2026),
            float(aggregate["expectancy_r"] or -999.0),
        )

        rows.append({
            "variant_id": variant.variant_id,
            "variant": asdict(variant),
            "aggregate_stressed": aggregate,
            "year_2025_stressed": m2025,
            "year_2026_partial_stressed": m2026,
            "quarterly_stressed": _quarterly_metrics(oos, cost_abs=v14.STRESS_COST_USD),
            "direction_stressed": _direction_metrics(oos, cost_abs=v14.STRESS_COST_USD),
            "concurrency": v14._concurrency(oos),
            "bootstrap": bootstrap,
            "entry_frequency_oos": _entry_frequency(oos, "2025-01-01", "2026-09-01"),
            "diagnostic_flags": {
                "aggregate_gate_pass": aggregate_pass,
                "current_2026_gate_pass": current_year_pass,
                "both_2025_2026_positive": both_years_positive,
                "bootstrap_positive": bootstrap_positive,
            },
            "_robustness_key": robustness_key,
        })

    ranked = sorted(rows, key=lambda x: x["_robustness_key"], reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["diagnostic_rank"] = rank
        row.pop("_robustness_key", None)

    stable = [
        row["variant_id"]
        for row in ranked
        if row["diagnostic_flags"]["aggregate_gate_pass"]
        and row["diagnostic_flags"]["current_2026_gate_pass"]
        and row["diagnostic_flags"]["both_2025_2026_positive"]
        and row["diagnostic_flags"]["bootstrap_positive"]
    ]

    return {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": v14.SYMBOL,
        "data_source": "Dukascopy Bank public BID H1 via dukascopy-python",
        "history": {
            "h1_rows": int(len(h1)),
            "h1_start": str(h1["time"].min()),
            "h1_end": str(h1["time"].max()),
        },
        "diagnostic_provenance": {
            "oos_previously_exposed": True,
            "selection_status": "POST_HOC_DIAGNOSTIC_ONLY",
            "note": (
                "2025-2026 OOS has already been inspected in V14/V15. V16 may rank robustness "
                "for forward DEMO challenger selection only and cannot confer execution authority."
            ),
        },
        "cost_usd_round_trip_stress": v14.STRESS_COST_USD,
        "aggregate_gate": AGGREGATE_GATE,
        "current_year_gate": CURRENT_YEAR_GATE,
        "stable_diagnostic_candidates": stable,
        "variants": ranked,
        "next_step": (
            "Use any stable candidate only as a forward DEMO challenger. Intraday V17 must be "
            "developed separately to target approximately five valid opportunities per day."
        ),
    }


def main() -> None:
    base.SYMBOLS = {v14.SYMBOL: base.SYMBOLS[v14.SYMBOL]}
    base.SLOW_START = pd.Timestamp("2012-01-01").to_pydatetime()
    print("FETCH XAUUSD H1 2012-2026")
    h1 = base.fetch_h1(v14.SYMBOL)
    report = build_report(h1)

    out = Path("research_output_xau_d1_staggered_robustness_v16")
    out.mkdir(exist_ok=True)
    path = out / "xau_d1_staggered_robustness_v16.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(
        "XAU_D1_STAGGERED_ROBUSTNESS_V16 "
        f"variants={len(report['variants'])} "
        f"stable={len(report['stable_diagnostic_candidates'])} "
        "promotion_eligible=0"
    )
    for row in report["variants"][:8]:
        a = row["aggregate_stressed"]
        y25 = row["year_2025_stressed"]
        y26 = row["year_2026_partial_stressed"]
        print(
            "V16_RANK "
            f"rank={row['diagnostic_rank']} id={row['variant_id']} "
            f"agg_n={a['trades']} agg_pf={a['profit_factor']} agg_exp={a['expectancy_r']} "
            f"y25_n={y25['trades']} y25_pf={y25['profit_factor']} y25_exp={y25['expectancy_r']} "
            f"y26_n={y26['trades']} y26_pf={y26['profit_factor']} y26_exp={y26['expectancy_r']} "
            f"flags={json.dumps(row['diagnostic_flags'], sort_keys=True)}"
        )
    print("Research only: execution_influence=false diagnostic_only=true")


if __name__ == "__main__":
    main()

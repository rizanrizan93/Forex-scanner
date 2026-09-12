from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import five_core_tournament_v1 as base
import xau_d1_boundary_sensitivity_v1 as boundary

CONTRACT = "XAU_D1_ROLLING_STABILITY_V1"
EXECUTION_INFLUENCE = False
SYMBOL = "XAUUSD"
DATA_END = pd.Timestamp("2026-09-01", tz="UTC")
COSTS = {
    "base_0.17_usd": 0.17,
    "stress_0.35_usd": 0.35,
}
MIN_TRADES_3Y = 30
MIN_TRADES_5Y = 50

# Preregistered before seeing rolling-window results. These thresholds do not
# alter the strategy and can only classify evidence for continued DEMO study.
GATE = {
    "base": {
        "min_positive_ratio_3y": 0.70,
        "min_positive_ratio_5y": 0.80,
        "min_latest_expectancy_3y": 0.0,
        "min_latest_expectancy_5y": 0.0,
        "min_worst_expectancy_5y": -0.05,
    },
    "stress": {
        "min_positive_ratio_3y": 0.60,
        "min_positive_ratio_5y": 0.70,
        "min_latest_expectancy_3y": 0.0,
        "min_latest_expectancy_5y": 0.0,
        "min_worst_expectancy_5y": -0.075,
    },
    "min_eligible_window_ratio": 0.90,
}


def _annual_windows(years: int, first_start: int, last_complete_start: int):
    out = []
    for year in range(first_start, last_complete_start + 1):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + years}-01-01", tz="UTC")
        out.append((f"{year}_{year + years - 1}", start, end, False))
    latest_start = DATA_END - pd.DateOffset(years=years)
    out.append(
        (
            f"LATEST_TRAILING_{years}Y",
            pd.Timestamp(latest_start),
            DATA_END,
            True,
        )
    )
    return out


WINDOWS = {
    "3Y": _annual_windows(3, 2012, 2022),
    "5Y": _annual_windows(5, 2012, 2020),
}


def _window_metrics(trades: pd.DataFrame, *, cost_abs: float, window_type: str):
    min_trades = MIN_TRADES_3Y if window_type == "3Y" else MIN_TRADES_5Y
    rows = []
    for label, start, end, latest in WINDOWS[window_type]:
        subset = trades[
            (trades["entry_time"] >= start) & (trades["entry_time"] < end)
        ]
        stressed = boundary._with_cost(subset, cost_abs)
        metrics = base.metrics(stressed)
        rows.append(
            {
                "window_type": window_type,
                "window": label,
                "start": str(start),
                "end_exclusive": str(end),
                "latest": latest,
                "eligible": int(metrics["trades"]) >= min_trades,
                **{k: v for k, v in metrics.items() if k != "annual_net_r"},
            }
        )
    return rows


def _summarize(rows):
    eligible = [row for row in rows if row["eligible"]]
    latest = [row for row in rows if row["latest"]]
    positive = [
        row for row in eligible
        if row["expectancy_r"] is not None and float(row["expectancy_r"]) > 0
    ]
    worst = min(
        (float(row["expectancy_r"]) for row in eligible if row["expectancy_r"] is not None),
        default=None,
    )
    return {
        "windows": len(rows),
        "eligible_windows": len(eligible),
        "eligible_ratio": len(eligible) / len(rows) if rows else 0.0,
        "positive_eligible_windows": len(positive),
        "positive_ratio": len(positive) / len(eligible) if eligible else 0.0,
        "worst_expectancy_r": worst,
        "latest": latest[0] if latest else None,
    }


def _gate(cost_label: str, summary_3y: dict, summary_5y: dict):
    thresholds = GATE["base"] if cost_label == "base_0.17_usd" else GATE["stress"]
    latest3 = summary_3y["latest"] or {}
    latest5 = summary_5y["latest"] or {}
    checks = {
        "eligible_ratio_3y": summary_3y["eligible_ratio"] >= GATE["min_eligible_window_ratio"],
        "eligible_ratio_5y": summary_5y["eligible_ratio"] >= GATE["min_eligible_window_ratio"],
        "positive_ratio_3y": summary_3y["positive_ratio"] >= thresholds["min_positive_ratio_3y"],
        "positive_ratio_5y": summary_5y["positive_ratio"] >= thresholds["min_positive_ratio_5y"],
        "latest_expectancy_3y": (
            bool(latest3.get("eligible"))
            and latest3.get("expectancy_r") is not None
            and float(latest3["expectancy_r"]) > thresholds["min_latest_expectancy_3y"]
        ),
        "latest_expectancy_5y": (
            bool(latest5.get("eligible"))
            and latest5.get("expectancy_r") is not None
            and float(latest5["expectancy_r"]) > thresholds["min_latest_expectancy_5y"]
        ),
        "worst_expectancy_5y": (
            summary_5y["worst_expectancy_r"] is not None
            and float(summary_5y["worst_expectancy_r"]) >= thresholds["min_worst_expectancy_5y"]
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    base.SYMBOLS = {SYMBOL: base.SYMBOLS[SYMBOL]}
    base.SLOW_START = datetime(2012, 1, 1)

    print("FETCH XAUUSD H1 2012-2026")
    h1 = base.fetch_h1(SYMBOL)
    d1 = boundary.aggregate_new_york_17(h1)
    trades = boundary.simulate(d1, "NY17_ROLLING")

    by_cost = {}
    csv_rows = []
    for cost_label, cost_abs in COSTS.items():
        rows3 = _window_metrics(trades, cost_abs=cost_abs, window_type="3Y")
        rows5 = _window_metrics(trades, cost_abs=cost_abs, window_type="5Y")
        summary3 = _summarize(rows3)
        summary5 = _summarize(rows5)
        gate = _gate(cost_label, summary3, summary5)
        by_cost[cost_label] = {
            "cost_abs_usd": cost_abs,
            "windows_3y": rows3,
            "windows_5y": rows5,
            "summary_3y": summary3,
            "summary_5y": summary5,
            "gate": gate,
        }
        for row in (*rows3, *rows5):
            csv_rows.append({"cost_label": cost_label, "cost_abs_usd": cost_abs, **row})

    overall_pass = all(block["gate"]["passed"] for block in by_cost.values())
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "symbol": SYMBOL,
        "strategy": "D1_TSMOM_60_200",
        "boundary": "17:00 America/New_York DST-aware",
        "data_source": "Dukascopy Bank public BID H1",
        "data_end_exclusive": str(DATA_END),
        "frozen_parameters": {
            "trend": "close vs EMA200",
            "momentum": "60D return same sign",
            "entry": "next D1 open",
            "stop_atr": boundary.STOP_ATR,
            "target_atr": boundary.TARGET_ATR,
            "max_hold_d1": boundary.MAX_HOLD_D1,
            "same_bar_policy": base.SAME_BAR_POLICY,
        },
        "minimum_trades": {"3Y": MIN_TRADES_3Y, "5Y": MIN_TRADES_5Y},
        "preregistered_gate": GATE,
        "by_cost": by_cost,
        "overall_pass_for_continued_demo": overall_pass,
    }

    out = Path("research_output_xau_rolling_stability_v1")
    out.mkdir(exist_ok=True)
    (out / "xau_d1_rolling_stability_v1.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(csv_rows).to_csv(out / "rolling_windows.csv", index=False)

    compact = []
    for label, block in by_cost.items():
        compact.append(
            {
                "cost": label,
                "positive_ratio_3y": block["summary_3y"]["positive_ratio"],
                "positive_ratio_5y": block["summary_5y"]["positive_ratio"],
                "worst_5y": block["summary_5y"]["worst_expectancy_r"],
                "latest_3y": block["summary_3y"]["latest"]["expectancy_r"],
                "latest_5y": block["summary_5y"]["latest"]["expectancy_r"],
                "passed": block["gate"]["passed"],
            }
        )
    print("# XAU D1 ROLLING STABILITY V1")
    print(pd.DataFrame(compact).to_string(index=False))
    print("overall_pass_for_continued_demo=", overall_pass)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

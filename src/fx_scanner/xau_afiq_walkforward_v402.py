from __future__ import annotations

"""V402 walk-forward aggregation utilities for V401 local-confirmation replay.

Each calendar year is replayed independently with a fixed pre-year warmup.
This prevents one giant O(N^2)-like zone metadata pass while preserving a
strictly causal evaluation. Aggregation is performed from the per-trade fixed
XAU price-unit PnL, not from averaged annual PF values.
"""

from math import inf
from statistics import fmean
from typing import Any, Iterable

CONTRACT = "XAU_RIZAN_AFIQ_WALKFORWARD_V402"
COST_STRESS_PRICE_UNITS = (0.0, 0.25, 0.50, 1.00)
MIN_TOTAL_TRADES_FOR_PROMOTION = 100
MIN_TRADES_PER_YEAR_FOR_ROBUST_YEAR = 5


def _pf(values: list[float]) -> float | None:
    positive = sum(value for value in values if value > 0)
    negative = -sum(value for value in values if value < 0)
    if negative == 0:
        return inf if positive > 0 else None
    return positive / negative


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics_from_trades(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted((dict(trade) for trade in trades), key=lambda row: str(row.get("entry_at") or ""))
    if not rows:
        return {
            "trades": 0,
            "win_rate": None,
            "fixed_price_pf": None,
            "expectancy_price": None,
            "net_price": 0.0,
            "max_drawdown_price": 0.0,
            "cost_stress": {},
        }
    pnl = [float(row["pnl_price"]) for row in rows]
    stress: dict[str, Any] = {}
    for cost in COST_STRESS_PRICE_UNITS:
        adjusted = [value - cost for value in pnl]
        stress[f"cost_{cost:.2f}"] = {
            "fixed_price_pf": _pf(adjusted),
            "expectancy_price": fmean(adjusted),
            "net_price": sum(adjusted),
            "max_drawdown_price": _max_drawdown(adjusted),
        }
    return {
        "trades": len(rows),
        "wins": sum(value > 0 for value in pnl),
        "losses": sum(value < 0 for value in pnl),
        "win_rate": sum(value > 0 for value in pnl) / len(pnl),
        "fixed_price_pf": _pf(pnl),
        "expectancy_price": fmean(pnl),
        "net_price": sum(pnl),
        "max_drawdown_price": _max_drawdown(pnl),
        "long_trades": sum(str(row.get("direction")) == "LONG" for row in rows),
        "short_trades": sum(str(row.get("direction")) == "SHORT" for row in rows),
        "cost_stress": stress,
    }


def aggregate_reports(reports: Iterable[dict[str, Any]], expected_years: Iterable[int]) -> dict[str, Any]:
    rows = [dict(report) for report in reports]
    expected = [int(year) for year in expected_years]
    present = sorted({int(report["target_year"]) for report in rows if report.get("target_year") is not None})
    variants = sorted(
        {
            name
            for report in rows
            for name in dict(report.get("variants") or {}).keys()
        }
    )
    out_variants: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for name in variants:
        trades: list[dict[str, Any]] = []
        by_year: dict[str, Any] = {}
        for report in rows:
            year = int(report["target_year"])
            payload = dict(dict(report.get("variants") or {}).get(name) or {})
            year_trades = [dict(trade) for trade in payload.get("trades") or []]
            trades.extend(year_trades)
            by_year[str(year)] = metrics_from_trades(year_trades)
        metrics = metrics_from_trades(trades)
        robust_years = [
            int(year)
            for year, metric in by_year.items()
            if int(metric.get("trades") or 0) >= MIN_TRADES_PER_YEAR_FOR_ROBUST_YEAR
        ]
        robust_year_pfs = [by_year[str(year)].get("fixed_price_pf") for year in robust_years]
        cost_pf = metrics.get("cost_stress", {}).get("cost_0.50", {}).get("fixed_price_pf")
        pf = metrics.get("fixed_price_pf")
        exp = metrics.get("expectancy_price")
        gates[name] = {
            "all_expected_years_present": present == expected,
            "total_trades_gte_100": int(metrics.get("trades") or 0) >= MIN_TOTAL_TRADES_FOR_PROMOTION,
            "fixed_price_pf_gte_1_5": pf is not None and pf != inf and float(pf) >= 1.5,
            "expectancy_price_positive": exp is not None and float(exp) > 0,
            "cost_0_50_pf_gte_1_2": cost_pf is not None and (cost_pf == inf or float(cost_pf) >= 1.2),
            "robust_years_pf_gte_1_0": bool(robust_year_pfs) and all(
                value is not None and (value == inf or float(value) >= 1.0)
                for value in robust_year_pfs
            ),
            "robust_year_count": len(robust_years),
        }
        out_variants[name] = {
            "metrics": metrics,
            "by_year": by_year,
            "robust_years": robust_years,
            "trades": trades,
        }
    return {
        "contract": CONTRACT,
        "source_contract": "XAU_RIZAN_AFIQ_LOCAL_CONFIRM_ENTRY_V401",
        "expected_years": expected,
        "present_years": present,
        "missing_years": [year for year in expected if year not in present],
        "variants": out_variants,
        "numeric_gates": gates,
        "promotion_eligible": False,
        "promotion_blockers": [
            "HISTORICAL_SPREAD_AND_COMMISSION_NOT_OBSERVED",
            "CAUSAL_EVENT_BLACKOUT_ARCHIVE_NOT_APPLIED",
            "PARAMETER_SELECTION_REQUIRES_HELD_OUT_VALIDATION",
        ],
    }

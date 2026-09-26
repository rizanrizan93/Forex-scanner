from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from .research_xau_h4_h1_m15_m5_portfolio_v233_aggregate import (
    _account_matrix,
    _dt,
    _load_v231_reversal,
    _rolling_three_year,
    _trade_metrics,
)
from .research_xau_h4_h1_sd_m15_m5_portfolio_v234_aggregate import (
    _load_continuation,
)

RESEARCH_VERSION = "XAU_CAUSAL_MTF_HEALTH_ROUTER_V235_1"
ARTIFACT_CONTRACT = "XAU_CAUSAL_MTF_HEALTH_ROUTER_V235_FULL_1"

HEALTH_WINDOW_DAYS = 126
MIN_COMPLETED_TRADES = 30
MIN_PROFIT_FACTOR = 1.10
MIN_EXPECTANCY_R = 0.05
HEALTH_FRICTION_POINTS = 0.50


def _health_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: list[float] = []
    for row in rows:
        risk = float(row.get("risk_points") or 0.0)
        if risk <= 0:
            continue
        values.append(
            (float(row.get("gross_points") or 0.0) - HEALTH_FRICTION_POINTS)
            / risk
        )
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "completed_trades": len(values),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "expectancy_r": sum(values) / len(values) if values else None,
        "win_rate": (
            len(wins) / (len(wins) + len(losses))
            if wins or losses else None
        ),
    }


def _health_pass(metrics: dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("completed_trades") or 0) >= MIN_COMPLETED_TRADES
        and float(metrics.get("profit_factor") or 0.0) >= MIN_PROFIT_FACTOR
        and float(metrics.get("expectancy_r") or -999.0) >= MIN_EXPECTANCY_R
    )


def route_causally(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            _dt(row["fill_at"]),
            str(row.get("variant_id") or ""),
            str(row.get("direction") or ""),
            str(row.get("slot") or ""),
        ),
    )
    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    routed: list[dict[str, Any]] = []
    checks = 0
    passed = 0
    stream_stats: dict[str, dict[str, int]] = {}

    for row in ordered:
        fill_at = _dt(row["fill_at"])
        key = (
            str(row.get("variant_id") or ""),
            str(row.get("direction") or ""),
        )
        stream = history.setdefault(key, [])
        cutoff = fill_at - timedelta(days=HEALTH_WINDOW_DAYS)
        eligible_history = [
            prior
            for prior in stream
            if cutoff <= _dt(prior["exit_at"]) < fill_at
        ]
        metrics = _health_metrics(eligible_history)
        is_on = _health_pass(metrics)
        checks += 1

        label = f"{key[0]}|{key[1]}"
        state = stream_stats.setdefault(
            label,
            {"checks": 0, "passed": 0, "routed_orders": 0},
        )
        state["checks"] += 1

        if is_on:
            passed += 1
            state["passed"] += 1
            state["routed_orders"] += 1
            routed.append(
                {
                    **row,
                    "engine": "V235_CAUSAL_HEALTH_ROUTED_CONTINUATION",
                    "trade_key": "V235|" + str(row.get("trade_key") or ""),
                    "health_at_entry": metrics,
                    "health_contract": {
                        "window_days": HEALTH_WINDOW_DAYS,
                        "minimum_completed_trades": MIN_COMPLETED_TRADES,
                        "minimum_profit_factor": MIN_PROFIT_FACTOR,
                        "minimum_expectancy_r": MIN_EXPECTANCY_R,
                        "friction_points": HEALTH_FRICTION_POINTS,
                    },
                }
            )

        # Every candidate remains shadow-observed regardless of gate state.
        # Future decisions may use it only after its exit is completed.
        stream.append(row)

    return routed, {
        "candidate_checks": checks,
        "health_passed_checks": passed,
        "activation_rate": passed / checks if checks else None,
        "streams": stream_stats,
    }


def _period(rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    return _trade_metrics(
        [row for row in rows if start <= int(row["year"]) <= end],
        friction=0.5,
    )


def aggregate(v234_root: str, v230_root: str) -> dict[str, Any]:
    raw = _load_continuation(v234_root)
    routed, health = route_causally(raw)
    reversal = _load_v231_reversal(v230_root)
    portfolio = sorted(
        reversal + routed,
        key=lambda row: (_dt(row["fill_at"]), row["trade_key"]),
    )

    full = _account_matrix(portfolio)
    eras: dict[str, Any] = {}
    for name, start, end in (
        ("train_2012_2018", 2012, 2018),
        ("test_2019_2024", 2019, 2024),
        ("holdout_2025_2026", 2025, 2026),
    ):
        subset = [row for row in portfolio if start <= int(row["year"]) <= end]
        eras[name] = _account_matrix(subset)

    rolling = _rolling_three_year(
        portfolio,
        friction=0.5,
        margin_fraction=0.50,
    )
    positive_rolling = sum(
        float(item["account"]["net_profit"]) > 0 for item in rolling
    )
    target_10k = any(
        bool(config["target_10000_reached"])
        for friction in full.values()
        for config in friction.values()
    )

    primary = full["friction_0.5"]["margin_50pct"]
    test_primary = eras["test_2019_2024"]["friction_0.5"]["margin_50pct"]
    holdout_primary = eras["holdout_2025_2026"]["friction_0.5"]["margin_50pct"]

    decision = "HOLD_RESEARCH_ONLY"
    if (
        float(test_primary["net_profit"]) > 0
        and float(holdout_primary["net_profit"]) > 0
        and positive_rolling >= 10
    ):
        decision = "PROSPECTIVE_SHADOW_CANDIDATE"

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "objective": "$200_TO_$10000_WITH_CAUSAL_SELF_QUALIFYING_MTF_FAMILIES",
        "health_contract": {
            "window_days": HEALTH_WINDOW_DAYS,
            "minimum_completed_trades": MIN_COMPLETED_TRADES,
            "minimum_profit_factor": MIN_PROFIT_FACTOR,
            "minimum_expectancy_r": MIN_EXPECTANCY_R,
            "health_friction_points": HEALTH_FRICTION_POINTS,
            "stream_identity": "TARGET_POLICY_X_DIRECTION",
            "calendar_or_era_input": False,
            "future_outcomes_used": False,
        },
        "raw_v234_orders": len(raw),
        "routed_v235_orders": len(routed),
        "health_diagnostics": health,
        "routed_trade_metrics": {
            "full_2012_2026": _trade_metrics(routed, friction=0.5),
            "train_2012_2018": _period(routed, 2012, 2018),
            "test_2019_2024": _period(routed, 2019, 2024),
            "holdout_2025_2026": _period(routed, 2025, 2026),
            "by_variant": {
                variant: _trade_metrics(
                    [row for row in routed if row["variant_id"] == variant],
                    friction=0.5,
                )
                for variant in sorted({str(row["variant_id"]) for row in raw})
            },
            "by_direction": {
                direction: _trade_metrics(
                    [row for row in routed if row["direction"] == direction],
                    friction=0.5,
                )
                for direction in ("LONG", "SHORT")
            },
        },
        "reversal_orders": len(reversal),
        "portfolio_candidate_orders": len(portfolio),
        "portfolio_full_2012_2026": full,
        "portfolio_era_restart": eras,
        "rolling_3y_friction_0_5_margin_50pct": rolling,
        "rolling_3y_positive_windows": positive_rolling,
        "rolling_3y_window_count": len(rolling),
        "historical_target_10000_reached_any_sizing": target_10k,
        "primary_friction_0_5_margin_50pct": primary,
        "decision": decision,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "methodology_note": (
            "V235 does not select a historical winning calendar era. Each V234 "
            "target-policy x direction stream is continuously shadow-scored from "
            "completed prior trades over 126 days. The frozen V47-style family "
            "health thresholds decide whether the next candidate is routed. "
            "All suppressed candidates remain in shadow history, preventing "
            "survivorship feedback."
        ),
    }


def run() -> int:
    v234_root = os.environ.get("XAU_V235_V234_DIR", "/tmp/v234-shards")
    v230_root = os.environ.get("XAU_V235_V230_DIR", "/tmp/v230-shards")
    output = Path(
        os.environ.get(
            "XAU_V235_OUTPUT",
            "artifacts/xau-causal-mtf-health-router-v235-full.json",
        )
    )
    result = aggregate(v234_root, v230_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    primary = result["primary_friction_0_5_margin_50pct"]
    print(
        "XAU_V235_FULL "
        f"raw={result['raw_v234_orders']} routed={result['routed_v235_orders']} "
        f"final50={primary['final_balance']:.2f} "
        f"dd50={primary['max_realized_drawdown']:.4f} "
        f"target10k={result['historical_target_10000_reached_any_sizing']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

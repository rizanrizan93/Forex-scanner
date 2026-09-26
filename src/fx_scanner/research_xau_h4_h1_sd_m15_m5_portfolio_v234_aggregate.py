from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

from .research_xau_h4_h1_m15_m5_portfolio_v233_aggregate import (
    FRICTIONS,
    MARGIN_FRACTIONS,
    _account_matrix,
    _dt,
    _load_v231_reversal,
    _rolling_three_year,
    _trade_metrics,
)

CONT_VERSION = "XAU_H4_H1_SD_M15_M5_CONTINUATION_V234_1"
RESEARCH_VERSION = "XAU_H4_H1_SD_M15_M5_PORTFOLIO_V234_1"
ARTIFACT_CONTRACT = "XAU_H4_H1_SD_M15_M5_PORTFOLIO_V234_FULL_1"

MIN_TRAIN_TRADES = 100
MIN_TRAIN_PF = 1.05
MIN_POSITIVE_TRAIN_YEARS = 4


def _load_continuation(root: str) -> list[dict[str, Any]]:
    files = sorted(
        glob.glob(
            os.path.join(root, "**", "xau-h4-h1-sd-m15-m5-continuation-v234-*.json"),
            recursive=True,
        )
    )
    if not files:
        raise RuntimeError("V234_CONTINUATION_SHARDS_MISSING")
    rows: list[dict[str, Any]] = []
    years: list[int] = []
    for path in files:
        payload = json.loads(Path(path).read_text())
        if payload.get("research_version") != CONT_VERSION:
            raise RuntimeError(f"V234_CONT_VERSION_MISMATCH:{path}")
        year = int(payload["year"])
        years.append(year)
        for raw in list(payload.get("trades") or []):
            row = dict(raw)
            row["engine"] = "CONTINUATION_V234"
            row["trade_key"] = "|".join(
                (
                    "V234",
                    str(row.get("variant_id") or ""),
                    str(row.get("h1_zone_id") or ""),
                    str(row.get("slot") or ""),
                    str(row.get("fill_at") or ""),
                )
            )
            rows.append(row)
    observed = sorted(set(years))
    expected = list(range(2012, 2027))
    if observed != expected:
        raise RuntimeError(f"V234_YEAR_COVERAGE_INVALID:{observed}")
    rows.sort(key=lambda row: (_dt(row["fill_at"]), row["trade_key"]))
    return rows


def _select(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    variants = sorted({str(row["variant_id"]) for row in rows})
    evidence: dict[str, Any] = {}
    eligible: list[tuple[float, float, str]] = []
    for variant in variants:
        train = [
            row
            for row in rows
            if str(row["variant_id"]) == variant
            and 2012 <= int(row["year"]) <= 2018
        ]
        metrics = _trade_metrics(train, friction=0.5)
        passed = bool(
            int(metrics["orders"]) >= MIN_TRAIN_TRADES
            and float(metrics.get("profit_factor") or 0.0) >= MIN_TRAIN_PF
            and float(metrics["net_points_fixed_0_01"]) > 0.0
            and int(metrics["positive_years"]) >= MIN_POSITIVE_TRAIN_YEARS
        )
        evidence[variant] = {
            "train_2012_2018": metrics,
            "selection_passed": passed,
        }
        if passed:
            eligible.append(
                (
                    float(metrics["net_points_fixed_0_01"]),
                    float(metrics.get("profit_factor") or 0.0),
                    variant,
                )
            )
    eligible.sort(reverse=True)
    return (eligible[0][2] if eligible else None), evidence


def _period(
    rows: list[dict[str, Any]],
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    return _trade_metrics(
        [row for row in rows if start <= int(row["year"]) <= end],
        friction=0.5,
    )


def aggregate(cont_root: str, v230_root: str) -> dict[str, Any]:
    continuation = _load_continuation(cont_root)
    reversal = _load_v231_reversal(v230_root)
    selected, selection = _select(continuation)
    selected_rows = (
        [row for row in continuation if str(row["variant_id"]) == selected]
        if selected is not None
        else []
    )
    portfolio = sorted(
        reversal + selected_rows,
        key=lambda row: (_dt(row["fill_at"]), row["trade_key"]),
    )

    validation: dict[str, Any] = {}
    if selected is not None:
        validation = {
            "selected_variant": selected,
            "train_2012_2018": _period(selected_rows, start=2012, end=2018),
            "test_2019_2024": _period(selected_rows, start=2019, end=2024),
            "holdout_2025_2026": _period(selected_rows, start=2025, end=2026),
            "full_2012_2026": _trade_metrics(selected_rows, friction=0.5),
            "by_direction": {
                direction: _trade_metrics(
                    [row for row in selected_rows if row["direction"] == direction],
                    friction=0.5,
                )
                for direction in ("LONG", "SHORT")
            },
            "by_slot": {
                slot: _trade_metrics(
                    [row for row in selected_rows if row["slot"] == slot],
                    friction=0.5,
                )
                for slot in ("NEAR_EDGE", "MIDPOINT")
            },
        }

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
        selected is not None
        and float(test_primary["net_profit"]) > 0.0
        and float(holdout_primary["net_profit"]) > 0.0
        and positive_rolling >= 10
    ):
        decision = "PROSPECTIVE_SHADOW_CANDIDATE"

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "objective": "$200_TO_$10000_H4_H1_SD_M15_M5",
        "selection_contract": {
            "train": [2012, 2018],
            "test": [2019, 2024],
            "holdout": [2025, 2026],
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "minimum_train_profit_factor": MIN_TRAIN_PF,
            "minimum_positive_train_years": MIN_POSITIVE_TRAIN_YEARS,
            "selection_score": "MAX_NET_POINTS_FRICTION_0_5_AFTER_GATES",
        },
        "constraints": {
            "initial_balance": 200.0,
            "leverage": "1:100",
            "max_lot": 0.50,
            "max_concurrent_positions": 2,
            "risk_percent_filter": None,
            "frictions": list(FRICTIONS),
            "margin_fraction_sensitivity": list(MARGIN_FRACTIONS),
        },
        "continuation_selection": selection,
        "continuation_validation": validation,
        "reversal_orders": len(reversal),
        "continuation_orders_selected": len(selected_rows),
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
            "The H1 supply/demand parent is evaluated only on its first causal touch. "
            "H4 trend, nested M15 and nested M5 zones must already exist before that touch. "
            "Target-policy selection uses 2012-2018 only; 2019-2024 and 2025-2026 are untouched "
            "by selection. V231 nested-terminal reversal remains frozen."
        ),
    }


def run() -> int:
    cont_root = os.environ.get("XAU_V234_CONTINUATION_DIR", "/tmp/v234-cont")
    v230_root = os.environ.get("XAU_V234_V230_DIR", "/tmp/v230-shards")
    output = Path(
        os.environ.get(
            "XAU_V234_FULL_OUTPUT",
            "artifacts/xau-h4-h1-sd-m15-m5-portfolio-v234-full.json",
        )
    )
    result = aggregate(cont_root, v230_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    primary = result["primary_friction_0_5_margin_50pct"]
    print(
        "XAU_V234_FULL "
        f"selected={result['continuation_validation'].get('selected_variant')} "
        f"orders={result['portfolio_candidate_orders']} "
        f"final50={primary['final_balance']:.2f} "
        f"dd50={primary['max_realized_drawdown']:.4f} "
        f"target10k={result['historical_target_10000_reached_any_sizing']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

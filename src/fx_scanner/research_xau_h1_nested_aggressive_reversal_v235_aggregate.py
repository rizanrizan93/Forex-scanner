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

RESEARCH_VERSION = "XAU_H1_NESTED_AGGRESSIVE_PORTFOLIO_V235_1"
ARTIFACT_CONTRACT = "XAU_H1_NESTED_AGGRESSIVE_PORTFOLIO_V235_FULL_1"
SOURCE_VERSION = "XAU_H1_NESTED_AGGRESSIVE_REVERSAL_V235_1"

MIN_TRAIN_ORDERS = 50
MIN_POSITIVE_TRAIN_YEARS = 4
MIN_TRAIN_PF = 1.05
TARGET_RUNGS = (0.50, 0.75, 1.00)
SLOTS = ("PROXIMAL", "MID")


def _load_v235(root: str) -> list[dict[str, Any]]:
    files = sorted(
        glob.glob(
            os.path.join(
                root,
                "**",
                "xau-h1-nested-aggressive-reversal-v235-*.json",
            ),
            recursive=True,
        )
    )
    if not files:
        raise RuntimeError("V235_YEAR_SHARDS_MISSING")
    rows: list[dict[str, Any]] = []
    years: list[int] = []
    for path in files:
        payload = json.loads(Path(path).read_text())
        if str(payload.get("research_version") or "") != SOURCE_VERSION:
            raise RuntimeError(f"V235_SOURCE_VERSION_MISMATCH:{path}")
        years.append(int(payload["year"]))
        for raw in list(payload.get("orders") or []):
            row = dict(raw)
            row["engine"] = "V235_H1_NESTED_AGGRESSIVE_REVERSAL"
            row["trade_key"] = "|".join(
                (
                    "V235",
                    str(row.get("episode_key") or ""),
                    str(row.get("variant_id") or ""),
                )
            )
            rows.append(row)
    observed = sorted(set(years))
    expected = list(range(2012, 2027))
    if observed != expected:
        raise RuntimeError(f"V235_YEAR_COVERAGE_INVALID:{observed}")
    rows.sort(key=lambda row: (_dt(row["fill_at"]), row["trade_key"]))
    return rows


def _variant_rows(
    rows: list[dict[str, Any]],
    variant: str,
) -> list[dict[str, Any]]:
    if variant.startswith("LADDER_T"):
        target = int(variant.rsplit("T", 1)[1]) / 100.0
        selected = [
            dict(row)
            for row in rows
            if abs(float(row.get("target_atr") or 0.0) - target) < 1e-9
            and str(row.get("slot") or "") in SLOTS
        ]
    else:
        selected = [
            dict(row)
            for row in rows
            if str(row.get("variant_id") or "") == variant
        ]
    for row in selected:
        row["portfolio_variant"] = variant
    selected.sort(key=lambda row: (_dt(row["fill_at"]), row["trade_key"]))
    return selected


def _variants() -> tuple[str, ...]:
    singles = tuple(
        f"V235_{slot}_T{int(round(target * 100)):03d}"
        for target in TARGET_RUNGS
        for slot in SLOTS
    )
    ladders = tuple(
        f"LADDER_T{int(round(target * 100)):03d}"
        for target in TARGET_RUNGS
    )
    return singles + ladders


def _train_episode_count(rows: list[dict[str, Any]]) -> int:
    return len({str(row.get("episode_key") or "") for row in rows})


def _select(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    evidence: dict[str, Any] = {}
    eligible: list[tuple[float, float, int, str]] = []
    for variant in _variants():
        candidate = _variant_rows(rows, variant)
        train = [
            row for row in candidate
            if 2012 <= int(row["year"]) <= 2018
        ]
        metrics = _trade_metrics(train, friction=0.5)
        episodes = _train_episode_count(train)
        passed = bool(
            metrics["orders"] >= MIN_TRAIN_ORDERS
            and episodes >= 30
            and float(metrics.get("profit_factor") or 0.0) >= MIN_TRAIN_PF
            and float(metrics["net_points_fixed_0_01"]) > 0
            and int(metrics["positive_years"]) >= MIN_POSITIVE_TRAIN_YEARS
        )
        evidence[variant] = {
            "train_2012_2018": metrics,
            "train_episode_count": episodes,
            "selection_passed": passed,
        }
        if passed:
            eligible.append(
                (
                    float(metrics["net_points_fixed_0_01"]),
                    float(metrics.get("profit_factor") or 0.0),
                    episodes,
                    variant,
                )
            )
    eligible.sort(reverse=True)
    return (eligible[0][3] if eligible else None), evidence


def _period_metrics(
    rows: list[dict[str, Any]],
    start: int,
    end: int,
) -> dict[str, Any]:
    subset = [row for row in rows if start <= int(row["year"]) <= end]
    return {
        **_trade_metrics(subset, friction=0.5),
        "episode_count": _train_episode_count(subset),
    }


def aggregate(v235_root: str, v230_root: str) -> dict[str, Any]:
    raw = _load_v235(v235_root)
    reversal = _load_v231_reversal(v230_root)
    selected, selection = _select(raw)
    selected_rows = _variant_rows(raw, selected) if selected is not None else []

    validation: dict[str, Any] = {}
    if selected is not None:
        validation = {
            "selected_variant": selected,
            "train_2012_2018": _period_metrics(selected_rows, 2012, 2018),
            "test_2019_2024": _period_metrics(selected_rows, 2019, 2024),
            "holdout_2025_2026": _period_metrics(selected_rows, 2025, 2026),
            "full_2012_2026": {
                **_trade_metrics(selected_rows, friction=0.5),
                "episode_count": _train_episode_count(selected_rows),
            },
        }

    portfolio = sorted(
        reversal + selected_rows,
        key=lambda row: (_dt(row["fill_at"]), row["trade_key"]),
    )
    full = _account_matrix(portfolio)
    reversal_only = _account_matrix(reversal)

    eras: dict[str, Any] = {}
    for name, start, end in (
        ("train_2012_2018", 2012, 2018),
        ("test_2019_2024", 2019, 2024),
        ("holdout_2025_2026", 2025, 2026),
    ):
        subset = [row for row in portfolio if start <= int(row["year"]) <= end]
        eras[name] = _account_matrix(subset)

    rolling = _rolling_three_year(portfolio)
    rolling_positive = sum(
        float(item["account"]["net_profit"]) > 0 for item in rolling
    )
    target10k = any(
        bool(config["target_10000_reached"])
        for friction in full.values()
        for config in friction.values()
    )

    decision = "HOLD_RESEARCH_ONLY"
    if selected is not None:
        test = validation["test_2019_2024"]
        recent = validation["holdout_2025_2026"]
        if (
            float(test["net_points_fixed_0_01"]) > 0
            and float(test.get("profit_factor") or 0.0) > 1.0
            and int(test["orders"]) >= 30
            and float(recent["net_points_fixed_0_01"]) > 0
            and float(recent.get("profit_factor") or 0.0) > 1.0
            and int(recent["orders"]) >= 10
        ):
            decision = "RETROSPECTIVE_STABILITY_PASS_PROSPECTIVE_REQUIRED"

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "objective": "$200_TO_$10000_WITH_SECOND_REVERSAL_ALPHA",
        "hypothesis_origin": {
            "source": "V185_2022_2026_HOLDOUT_DIAGNOSTIC",
            "observed_subgroup": (
                "H1_LONG_MULTI_HTF_NESTING_AGGRESSIVE_APPROACH"
            ),
            "observed_n": 30,
            "observed_hold_precision": 0.8333333333333334,
            "observed_wilson_lower_95": 0.6643564949358397,
            "governance": (
                "Because the subgroup was discovered using later historical data, "
                "all V235 era results are retrospective falsification/stability "
                "evidence, not pristine OOS promotion evidence."
            ),
        },
        "selection_contract": {
            "selection_period": [2012, 2018],
            "test_period": [2019, 2024],
            "recent_period": [2025, 2026],
            "variants": list(_variants()),
            "minimum_train_orders": MIN_TRAIN_ORDERS,
            "minimum_train_episodes": 30,
            "minimum_train_pf": MIN_TRAIN_PF,
            "minimum_positive_train_years": MIN_POSITIVE_TRAIN_YEARS,
            "selection_score": "MAX_NET_POINTS_FRICTION_0_5_AFTER_GATES",
        },
        "account_contract": {
            "initial_balance": 200.0,
            "leverage": "1:100",
            "max_lot": 0.50,
            "max_concurrent_positions": 2,
            "risk_percent_filter": None,
            "frictions": list(FRICTIONS),
            "margin_fraction_sensitivity": list(MARGIN_FRACTIONS),
        },
        "v235_selection": selection,
        "v235_validation": validation,
        "v231_reversal_orders": len(reversal),
        "v235_selected_orders": len(selected_rows),
        "portfolio_candidate_orders": len(portfolio),
        "v231_only_account_matrix": reversal_only,
        "combined_account_matrix": full,
        "combined_era_restart": eras,
        "rolling_3y_friction_0_5_margin_50pct": rolling,
        "rolling_3y_positive_windows": rolling_positive,
        "rolling_3y_window_count": len(rolling),
        "historical_target_10000_reached_any_sizing": target10k,
        "decision": decision,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def run() -> int:
    result = aggregate(
        os.getenv("XAU_V235_SHARD_DIR", "/tmp/v235-shards"),
        os.getenv("XAU_V235_V230_DIR", "/tmp/v230-shards"),
    )
    output = Path(
        os.getenv(
            "XAU_V235_FULL_OUTPUT",
            "artifacts/xau-h1-nested-aggressive-portfolio-v235-full.json",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    selected = result["v235_validation"].get("selected_variant")
    primary = result["combined_account_matrix"]["friction_0.5"]["fixed_0_01"]
    dynamic = result["combined_account_matrix"]["friction_0.5"]["margin_50pct"]
    print(
        "XAU_V235_FULL "
        f"selected={selected} "
        f"fixed_final={primary['final_balance']:.2f} "
        f"margin50_final={dynamic['final_balance']:.2f} "
        f"target10k={result['historical_target_10000_reached_any_sizing']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from .research_xau_v229_break_even_v244 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MANAGEMENT_VARIANTS,
    POLICY_EFFECT,
    RESEARCH_VERSION,
)
from .research_xau_v229_historical_v242 import effective_trades, summarize_trades

ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026_YTD": (2025, 2026),
}
CONFIGURED_ACCEPTANCE = {
    "win_rate_min": 0.55,
    "profit_factor_min": 1.30,
    "expectancy_r_min": 0.15,
    "aggregate_trades_min": 250,
}


def _shard_dir() -> Path:
    path = Path(os.getenv("XAU_V244_SHARD_DIR", "/tmp/xau-v244-shards"))
    if not path.exists():
        raise SystemExit(f"XAU_V244_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "XAU_V244_FULL_OUTPUT",
            "artifacts/xau-v229-break-even-v244-full.json",
        )
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(path.rglob("xau-v229-break-even-v244-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            rows.append(payload)
    rows.sort(key=lambda row: int(row["year"]))
    return rows


def _selected(
    rows: Sequence[dict[str, Any]],
    *,
    variant: str,
    cost_mode: str,
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("management_variant") or "").upper() == str(variant).upper()
        and str(row.get("cost_mode") or "").upper() == str(cost_mode).upper()
    ]


def _completed(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    ]


def _max_drawdown_r(rows: Sequence[dict[str, Any]]) -> float:
    completed = _completed(rows)
    completed.sort(
        key=lambda row: (
            str(row.get("exit_at") or ""),
            str(row.get("entry_at") or ""),
            str(row.get("plan_id") or ""),
            int(row.get("slot") or 0),
        )
    )
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for row in completed:
        equity += float(row.get("net_r") or 0.0)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return float(maximum)


def _metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output = dict(summarize_trades(rows))
    output["max_drawdown_r"] = _max_drawdown_r(rows)
    completed = _completed(rows)
    output["be_triggered"] = sum(bool(row.get("be_triggered")) for row in completed)
    output["be_stop_exits"] = sum(
        str(row.get("reason") or "").startswith("NET_BE_STOP_HIT")
        for row in completed
    )
    return output


def _breakdown(
    rows: Sequence[dict[str, Any]],
    *,
    key: str,
    values: Sequence[Any],
) -> dict[str, Any]:
    return {
        str(value): _metrics(
            [
                dict(row)
                for row in rows
                if str(row.get(key) or "").upper() == str(value).upper()
            ]
        )
        for value in values
    }


def _era_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected = [
            dict(row)
            for row in rows
            if start <= int(row.get("year") or 0) <= end
        ]
        output[name] = _metrics(selected)
    return output


def _official_numeric_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "trade_count": int(metrics.get("completed") or 0)
        >= CONFIGURED_ACCEPTANCE["aggregate_trades_min"],
        "win_rate": metrics.get("win_rate") is not None
        and float(metrics["win_rate"]) >= CONFIGURED_ACCEPTANCE["win_rate_min"],
        "profit_factor": metrics.get("profit_factor_r") is not None
        and float(metrics["profit_factor_r"]) >= CONFIGURED_ACCEPTANCE["profit_factor_min"],
        "expectancy": metrics.get("expectancy_r") is not None
        and float(metrics["expectancy_r"]) >= CONFIGURED_ACCEPTANCE["expectancy_r_min"],
    }
    return {
        "checks": checks,
        "all_numeric_gates_met": all(checks.values()),
        "thresholds": dict(CONFIGURED_ACCEPTANCE),
    }


def _positive_era(metrics: dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("completed") or 0) >= 30
        and metrics.get("profit_factor_r") is not None
        and float(metrics["profit_factor_r"]) > 1.0
        and metrics.get("expectancy_r") is not None
        and float(metrics["expectancy_r"]) > 0.0
    )


def _pair_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("plan_id") or ""),
        str(row.get("cost_mode") or "").upper(),
        int(row.get("slot") or 0),
    )


def _transition_report(
    effective: Sequence[dict[str, Any]],
    *,
    variant: str,
    cost_mode: str,
) -> dict[str, Any]:
    baseline = {
        _pair_key(row): dict(row)
        for row in effective
        if str(row.get("management_variant") or "") == "BASELINE"
        and str(row.get("cost_mode") or "").upper() == cost_mode
        and str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    }
    managed = {
        _pair_key(row): dict(row)
        for row in effective
        if str(row.get("management_variant") or "") == variant
        and str(row.get("cost_mode") or "").upper() == cost_mode
        and str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    }

    transitions: dict[str, int] = {}
    delta_r = 0.0
    paired = 0
    for key, left in baseline.items():
        right = managed.get(key)
        if right is None:
            continue
        paired += 1
        transition = f"{left.get('state')}->{right.get('state')}"
        transitions[transition] = transitions.get(transition, 0) + 1
        delta_r += float(right.get("net_r") or 0.0) - float(left.get("net_r") or 0.0)

    return {
        "paired_completed": paired,
        "transitions": transitions,
        "total_delta_r": float(delta_r),
        "mean_delta_r": None if paired == 0 else float(delta_r / paired),
    }


def _variant_report(
    effective: Sequence[dict[str, Any]],
    *,
    variant: str,
) -> dict[str, Any]:
    base_rows = _selected(effective, variant=variant, cost_mode="BASE")
    stress_rows = _selected(effective, variant=variant, cost_mode="STRESS")
    base = _metrics(base_rows)
    stress = _metrics(stress_rows)
    base_eras = _era_metrics(base_rows)
    stress_eras = _era_metrics(stress_rows)
    return {
        "variant": variant,
        "trigger_r": MANAGEMENT_VARIANTS[variant],
        "base": base,
        "stress": stress,
        "base_eras": base_eras,
        "stress_eras": stress_eras,
        "base_source": _breakdown(
            base_rows,
            key="candidate_source",
            values=("H4", "H1", "M15"),
        ),
        "stress_source": _breakdown(
            stress_rows,
            key="candidate_source",
            values=("H4", "H1", "M15"),
        ),
        "base_slot": _breakdown(
            base_rows,
            key="slot",
            values=(1, 2, 3, 4),
        ),
        "stress_slot": _breakdown(
            stress_rows,
            key="slot",
            values=(1, 2, 3, 4),
        ),
        "official_numeric_base": _official_numeric_gate(base),
        "official_numeric_stress": _official_numeric_gate(stress),
        "all_base_eras_positive": all(_positive_era(row) for row in base_eras.values()),
        "all_stress_eras_positive": all(_positive_era(row) for row in stress_eras.values()),
        "transition_base": (
            None
            if variant == "BASELINE"
            else _transition_report(effective, variant=variant, cost_mode="BASE")
        ),
        "transition_stress": (
            None
            if variant == "BASELINE"
            else _transition_report(effective, variant=variant, cost_mode="STRESS")
        ),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) < 15:
        raise SystemExit(f"XAU_V244_EXPECTED_15_SHARDS:{len(shards)}")

    plans: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        plans.extend(dict(row) for row in list(shard.get("plans") or []))
        trades.extend(dict(row) for row in list(shard.get("trades") or []))
        yearly[str(year)] = {
            "plans": int(shard.get("plan_count") or 0),
            "trade_records": int(shard.get("trade_record_count") or 0),
            "partial_current_year": bool(shard.get("partial_current_year")),
        }

    effective, cancel_at = effective_trades(plans, trades)
    variants = {
        variant: _variant_report(effective, variant=variant)
        for variant in MANAGEMENT_VARIANTS
    }

    baseline = variants["BASELINE"]
    candidates: list[str] = []
    for variant in ("BE_0_5R", "BE_1_0R"):
        report = variants[variant]
        base = dict(report["base"])
        stress = dict(report["stress"])
        if (
            int(base.get("completed") or 0) >= 250
            and base.get("profit_factor_r") is not None
            and float(base["profit_factor_r"]) > float(baseline["base"]["profit_factor_r"])
            and base.get("expectancy_r") is not None
            and float(base["expectancy_r"]) > float(baseline["base"]["expectancy_r"])
            and stress.get("profit_factor_r") is not None
            and float(stress["profit_factor_r"]) > float(baseline["stress"]["profit_factor_r"])
            and stress.get("expectancy_r") is not None
            and float(stress["expectancy_r"]) > float(baseline["stress"]["expectancy_r"])
            and bool(report["all_stress_eras_positive"])
        ):
            candidates.append(variant)

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "symbol": "XAUUSD",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "parent_plan_count": len(plans),
        "raw_trade_record_count": len(trades),
        "parent_cancel_count": len(cancel_at),
        "method": {
            "upstream": "XAU_V229_HISTORICAL_EXECUTION_V242_1",
            "variants": dict(MANAGEMENT_VARIANTS),
            "activation_clock": "NEXT_M1_BAR_AFTER_TRIGGER_BAR",
            "parameter_search": False,
            "pre_registered_management_variants": True,
            "validation_classification": "RETROSPECTIVE_MANAGEMENT_ABLATION_NOT_INDEPENDENT_OOS",
        },
        "variants": variants,
        "forward_shadow_candidates": candidates,
        "decision": (
            "FORWARD_SHADOW_MANAGEMENT_CANDIDATE_FOUND"
            if candidates
            else "NO_ROBUST_BREAK_EVEN_VARIANT_FOUND"
        ),
        "promotion": {
            "execution_promotion_allowed": False,
            "model_performance_persistence_eligible": False,
            "independent_oos_pass": False,
            "forward_demo_pass": False,
            "reason": (
                "V244 tests only two pre-registered BE rules on the same retrospective "
                "XAU universe as V242. Positive results may nominate a forward-shadow "
                "management rule but cannot authorize DEMO execution changes."
            ),
        },
        "yearly": yearly,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    print(
        "XAU_V229_BREAK_EVEN_V244_FULL "
        f"baseline_pf={variants['BASELINE']['base']['profit_factor_r']} "
        f"be05_pf={variants['BE_0_5R']['base']['profit_factor_r']} "
        f"be10_pf={variants['BE_1_0R']['base']['profit_factor_r']} "
        f"be05_stress_pf={variants['BE_0_5R']['stress']['profit_factor_r']} "
        f"be10_stress_pf={variants['BE_1_0R']['stress']['profit_factor_r']} "
        f"candidates={','.join(candidates) if candidates else 'NONE'} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

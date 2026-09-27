from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from .research_xau_v229_historical_v242 import effective_trades, summarize_trades
from .research_xau_v229_regime_admission_v243 import (
    ARTIFACT_CONTRACT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RESEARCH_VERSION,
    VARIANT_IDS,
    variant_match,
)

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
    path = Path(os.getenv("XAU_V243_SHARD_DIR", "/tmp/xau-v243-shards"))
    if not path.exists():
        raise SystemExit(f"XAU_V243_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "XAU_V243_FULL_OUTPUT",
            "artifacts/xau-v229-regime-admission-v243-full.json",
        )
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(path.rglob("xau-v229-regime-admission-v243-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            rows.append(payload)
    rows.sort(key=lambda row: int(row["year"]))
    return rows


def _filter_cost(rows: Sequence[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    wanted = str(mode).upper()
    return [dict(row) for row in rows if str(row.get("cost_mode") or "").upper() == wanted]


def _max_drawdown_r(rows: Sequence[dict[str, Any]]) -> float:
    completed = [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    ]
    completed.sort(key=lambda row: (str(row.get("exit_at") or ""), str(row.get("entry_at") or "")))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in completed:
        equity += float(row.get("net_r") or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return float(max_dd)


def _metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = dict(summarize_trades(rows))
    out["max_drawdown_r"] = _max_drawdown_r(rows)
    return out


def _official_numeric_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "trade_count": int(metrics.get("completed") or 0) >= CONFIGURED_ACCEPTANCE["aggregate_trades_min"],
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


def _era_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected = [dict(row) for row in rows if start <= int(row.get("year") or 0) <= end]
        output[name] = _metrics(selected)
    return output


def _positive_era(metrics: dict[str, Any]) -> bool:
    return bool(
        int(metrics.get("completed") or 0) >= 30
        and metrics.get("profit_factor_r") is not None
        and float(metrics["profit_factor_r"]) > 1.0
        and metrics.get("expectancy_r") is not None
        and float(metrics["expectancy_r"]) > 0.0
    )


def _forward_shadow_screen(
    *,
    base: dict[str, Any],
    stress: dict[str, Any],
    stress_eras: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "base_trades_250": int(base.get("completed") or 0) >= 250,
        "base_pf_1_10": base.get("profit_factor_r") is not None
        and float(base["profit_factor_r"]) >= 1.10,
        "base_expectancy_0_05": base.get("expectancy_r") is not None
        and float(base["expectancy_r"]) >= 0.05,
        "stress_pf_1_05": stress.get("profit_factor_r") is not None
        and float(stress["profit_factor_r"]) >= 1.05,
        "stress_expectancy_0_02": stress.get("expectancy_r") is not None
        and float(stress["expectancy_r"]) >= 0.02,
        "all_stress_eras_positive": all(_positive_era(row) for row in stress_eras.values()),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "purpose": "RESEARCH_FORWARD_SHADOW_CANDIDATE_ONLY",
        "execution_authority": False,
    }


def _variant_report(
    effective: Sequence[dict[str, Any]],
    *,
    variant_id: str,
) -> dict[str, Any]:
    selected = [dict(row) for row in effective if variant_match(dict(row), variant_id)]
    base_rows = _filter_cost(selected, "BASE")
    stress_rows = _filter_cost(selected, "STRESS")
    base = _metrics(base_rows)
    stress = _metrics(stress_rows)
    base_eras = _era_metrics(base_rows)
    stress_eras = _era_metrics(stress_rows)
    return {
        "variant_id": variant_id,
        "base": base,
        "stress": stress,
        "base_eras": base_eras,
        "stress_eras": stress_eras,
        "official_numeric_base": _official_numeric_gate(base),
        "official_numeric_stress": _official_numeric_gate(stress),
        "forward_shadow_screen": _forward_shadow_screen(
            base=base,
            stress=stress,
            stress_eras=stress_eras,
        ),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) < 15:
        raise SystemExit(f"XAU_V243_EXPECTED_15_SHARDS:{len(shards)}")

    plans: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        plans.extend(dict(row) for row in list(shard.get("plans") or []))
        trades.extend(dict(row) for row in list(shard.get("trades") or []))
        yearly[str(year)] = {
            "plans": int(shard.get("plan_count") or 0),
            "regime_points": int(shard.get("regime_point_count") or 0),
            "alignment_counts": dict(shard.get("plan_regime_alignment_counts") or {}),
            "partial_current_year": bool(shard.get("partial_current_year")),
        }

    effective, cancel_at = effective_trades(plans, trades)
    variants = {
        variant_id: _variant_report(effective, variant_id=variant_id)
        for variant_id in VARIANT_IDS
    }
    baseline = dict(variants["ALL_BASELINE"]["base"])
    baseline_pf = baseline.get("profit_factor_r")
    baseline_exp = baseline.get("expectancy_r")
    for report in variants.values():
        base = dict(report["base"])
        report["delta_vs_baseline_base"] = {
            "completed": int(base.get("completed") or 0) - int(baseline.get("completed") or 0),
            "profit_factor_r": (
                None
                if base.get("profit_factor_r") is None or baseline_pf is None
                else float(base["profit_factor_r"]) - float(baseline_pf)
            ),
            "expectancy_r": (
                None
                if base.get("expectancy_r") is None or baseline_exp is None
                else float(base["expectancy_r"]) - float(baseline_exp)
            ),
        }

    shadow_candidates = [
        variant_id
        for variant_id, report in variants.items()
        if bool(dict(report.get("forward_shadow_screen") or {}).get("passed"))
    ]

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
            "upstream_strategy": "CURRENT_V229_STYLE_DEPTH_2_PRETOUCH_2_M5_CONFIRMATION",
            "regime_engine": "XAU_HTF_STRATEGIC_REGIME_V180",
            "regime_inputs": "COMPLETED_D1_H4_ONLY",
            "variant_ids": list(VARIANT_IDS),
            "parameter_search": False,
            "variant_family_pre_registered": True,
            "validation_classification": "RETROSPECTIVE_REGIME_ABLATION_NOT_INDEPENDENT_OOS",
        },
        "variants": variants,
        "shadow_candidate_variants": shadow_candidates,
        "decision": (
            "FORWARD_SHADOW_CANDIDATE_FOUND"
            if shadow_candidates
            else "NO_ROBUST_REGIME_VARIANT_FOUND"
        ),
        "promotion": {
            "execution_promotion_allowed": False,
            "model_performance_persistence_eligible": False,
            "independent_oos_pass": False,
            "forward_demo_pass": False,
            "reason": (
                "V243 is a retrospective causal regime ablation over the same XAU historical "
                "universe used by V225.2/V229 research. It can nominate forward-shadow variants "
                "but cannot authorize DEMO execution changes."
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
        "XAU_V229_REGIME_ADMISSION_V243_FULL "
        f"plans={len(plans)} baseline_pf={variants['ALL_BASELINE']['base']['profit_factor_r']} "
        f"aligned_pf={variants['REGIME_ALIGNED']['base']['profit_factor_r']} "
        f"aligned_stress_pf={variants['REGIME_ALIGNED']['stress']['profit_factor_r']} "
        f"shadow_candidates={','.join(shadow_candidates) if shadow_candidates else 'NONE'} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

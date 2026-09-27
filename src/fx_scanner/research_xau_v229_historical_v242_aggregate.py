from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .research_xau_v229_historical_v242 import (
    ARTIFACT_CONTRACT,
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    CHILD_LOT,
    COMMISSION_PIPS_ROUND_TRIP,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RESEARCH_VERSION,
    STRESS_SLIPPAGE_MULTIPLIER,
    STRESS_SPREAD_MULTIPLIER,
    effective_trades,
    summarize_trades,
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
    path = Path(os.getenv("XAU_V242_SHARD_DIR", "/tmp/xau-v242-shards"))
    if not path.exists():
        raise SystemExit(f"XAU_V242_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "XAU_V242_FULL_OUTPUT",
            "artifacts/xau-v229-historical-v242-full.json",
        )
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for file in sorted(path.rglob("xau-v229-historical-v242-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            output.append(payload)
    output.sort(key=lambda row: int(row["year"]))
    return output


def _filter_cost(rows: Sequence[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    wanted = str(mode).upper()
    return [
        dict(row)
        for row in rows
        if str(row.get("cost_mode") or "").upper() == wanted
    ]


def _completed(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("state") or "") in {"WIN", "LOSS", "BREAKEVEN"}
    ]


def _max_drawdown_r(rows: Sequence[dict[str, Any]]) -> float:
    completed = _completed(rows)
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
    summary = dict(summarize_trades(rows))
    summary["max_drawdown_r"] = _max_drawdown_r(rows)
    return summary


def _slot_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"L{slot}": _metrics(
            [dict(row) for row in rows if int(row.get("slot") or 0) == slot]
        )
        for slot in range(1, 5)
    }


def _source_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        source: _metrics(
            [
                dict(row)
                for row in rows
                if str(row.get("candidate_source") or "").upper() == source
            ]
        )
        for source in ("H4", "H1", "M15")
    }


def _direction_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        direction: _metrics(
            [
                dict(row)
                for row in rows
                if str(row.get("direction") or "").upper() == direction
            ]
        )
        for direction in ("LONG", "SHORT")
    }


def _source_slot_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for source in ("H4", "H1", "M15"):
        output[source] = {}
        for slot in range(1, 5):
            selected = [
                dict(row)
                for row in rows
                if str(row.get("candidate_source") or "").upper() == source
                and int(row.get("slot") or 0) == slot
            ]
            output[source][f"L{slot}"] = _metrics(selected)
    return output


def _era_reports(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        selected = [
            dict(row)
            for row in rows
            if start <= int(row.get("year") or 0) <= end
        ]
        output[name] = {
            "years": [start, end],
            "summary": _metrics(selected),
            "slot_breakdown": _slot_breakdown(selected),
            "source_breakdown": _source_breakdown(selected),
            "direction_breakdown": _direction_breakdown(selected),
            "source_slot_breakdown": _source_slot_breakdown(selected),
        }
    return output


def _numeric_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    trades = int(metrics.get("completed") or 0)
    win_rate = metrics.get("win_rate")
    pf = metrics.get("profit_factor_r")
    exp = metrics.get("expectancy_r")
    checks = {
        "trade_count": trades >= CONFIGURED_ACCEPTANCE["aggregate_trades_min"],
        "win_rate": win_rate is not None
        and float(win_rate) >= CONFIGURED_ACCEPTANCE["win_rate_min"],
        "profit_factor": pf is not None
        and float(pf) >= CONFIGURED_ACCEPTANCE["profit_factor_min"],
        "expectancy": exp is not None
        and float(exp) >= CONFIGURED_ACCEPTANCE["expectancy_r_min"],
    }
    return {
        "checks": checks,
        "all_numeric_gates_met": all(checks.values()),
        "thresholds": dict(CONFIGURED_ACCEPTANCE),
    }


def _era_robustness(eras: dict[str, Any]) -> dict[str, Any]:
    rows = {}
    for name, payload in eras.items():
        metrics = dict(payload.get("summary") or {})
        pf = metrics.get("profit_factor_r")
        exp = metrics.get("expectancy_r")
        n = int(metrics.get("completed") or 0)
        rows[name] = {
            "completed": n,
            "profit_factor_r": pf,
            "expectancy_r": exp,
            "positive": bool(
                n >= 30
                and pf is not None
                and float(pf) > 1.0
                and exp is not None
                and float(exp) > 0.0
            ),
        }
    return {
        "eras": rows,
        "all_eras_positive": bool(rows) and all(row["positive"] for row in rows.values()),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) < 15:
        raise SystemExit(f"XAU_V242_EXPECTED_15_SHARDS:{len(shards)}")

    plans: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        plans.extend(dict(row) for row in list(shard.get("plans") or []))
        trades.extend(dict(row) for row in list(shard.get("trades") or []))
        yearly[str(year)] = {
            "partial_current_year": bool(shard.get("partial_current_year")),
            "parents": int(shard.get("parent_h4_first_touch_count") or 0),
            "plans": int(shard.get("plan_count") or 0),
            "trade_records": int(shard.get("trade_record_count") or 0),
            "skips": dict(shard.get("skips") or {}),
        }

    effective, cancel_at = effective_trades(plans, trades)
    base = _filter_cost(effective, "BASE")
    stress = _filter_cost(effective, "STRESS")

    base_summary = _metrics(base)
    stress_summary = _metrics(stress)
    base_eras = _era_reports(base)
    stress_eras = _era_reports(stress)
    base_gate = _numeric_gate(base_summary)
    stress_gate = _numeric_gate(stress_summary)

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "symbol": "XAUUSD",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "current_year_partial": bool(shards[-1].get("partial_current_year")),
        "current_year_data_end": dict(shards[-1].get("price_provenance") or {}).get("window_end"),
        "parent_plan_count": len(plans),
        "raw_trade_record_count": len(trades),
        "parent_cancel_count": len(cancel_at),
        "method": {
            "strategy": "CURRENT_V229_STYLE_DEPTH_2_PRETOUCH_2_M5_CONFIRMATION",
            "geometry_lineage": "XAU_V225_2_PLUS_V226_PLUS_V229",
            "same_sample_parameter_reuse": True,
            "validation_classification": "RETROSPECTIVE_CURRENT_PARAMETER_REPLAY_NOT_INDEPENDENT_OOS",
            "child_lot_reference": CHILD_LOT,
            "base_costs": {
                "spread_proxy_pips": BASE_SPREAD_PIPS,
                "slippage_pips": BASE_SLIPPAGE_PIPS,
                "commission_pips_round_trip": COMMISSION_PIPS_ROUND_TRIP,
                "spread_provenance": (
                    "CTRADER_XAU_M15_RESEARCH_CURRENT_QUOTE_PROXY_MEDIAN_2026_09_19; "
                    "NOT_HISTORICAL_SPREAD_SERIES"
                ),
            },
            "stress_costs": {
                "spread_multiplier": STRESS_SPREAD_MULTIPLIER,
                "slippage_multiplier": STRESS_SLIPPAGE_MULTIPLIER,
            },
            "ambiguous_bar_policy": "STOP_FIRST",
            "target_after_fill_guard": "REJECT_IF_TARGET_NOT_FAVORABLE_AFTER_COSTS",
            "parent_supersession": "NEXT_VALID_PARENT_PLAN_CANCELS_UNFILLED_CHILDREN",
        },
        "base": {
            "summary": base_summary,
            "numeric_acceptance": base_gate,
            "slot_breakdown": _slot_breakdown(base),
            "source_breakdown": _source_breakdown(base),
            "direction_breakdown": _direction_breakdown(base),
            "source_slot_breakdown": _source_slot_breakdown(base),
            "eras": base_eras,
            "era_robustness": _era_robustness(base_eras),
        },
        "stress": {
            "summary": stress_summary,
            "numeric_acceptance": stress_gate,
            "slot_breakdown": _slot_breakdown(stress),
            "source_breakdown": _source_breakdown(stress),
            "direction_breakdown": _direction_breakdown(stress),
            "source_slot_breakdown": _source_slot_breakdown(stress),
            "eras": stress_eras,
            "era_robustness": _era_robustness(stress_eras),
        },
        "profitability_validation": {
            "retrospective_numeric_base_pass": base_gate["all_numeric_gates_met"],
            "retrospective_numeric_stress_pass": stress_gate["all_numeric_gates_met"],
            "independent_oos_pass": False,
            "forward_demo_pass": False,
            "model_performance_persistence_eligible": False,
            "status": "RETROSPECTIVE_ONLY_NOT_VALIDATED",
            "reason": (
                "Current V225.2/V229 XAU depth parameters were developed using the same "
                "2012-2026 historical universe. Even if retrospective PF/expectancy are positive, "
                "independent OOS/forward evidence is still required."
            ),
        },
        "yearly": yearly,
        "limitations": [
            (
                "V242 reconstructs the current V229 child-entry and structural-target mechanics "
                "from causal H4 first-touch candidates; it does not replay every historical "
                "dashboard focus/path decision."
            ),
            (
                "The current frozen V225.2 depth priors originate from XAU historical research "
                "that overlaps this replay period, so results are retrospective, not independent OOS."
            ),
            (
                "The fixed 37-pip spread is a cTrader current-quote proxy observed by the existing "
                "XAU research runtime, not a historical spread series. Stress results are mandatory."
            ),
            "2026 is year-to-date through the available HistData endpoint.",
            "No account-balance/lot compounding claim is made in V242.",
        ],
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    print(
        "XAU_V229_HISTORICAL_V242_FULL "
        f"plans={len(plans)} base_completed={base_summary['completed']} "
        f"base_wr={base_summary['win_rate']} base_pf={base_summary['profit_factor_r']} "
        f"base_exp_r={base_summary['expectancy_r']} base_dd_r={base_summary['max_drawdown_r']} "
        f"stress_pf={stress_summary['profit_factor_r']} stress_exp_r={stress_summary['expectancy_r']} "
        f"retro_base_gate={int(base_gate['all_numeric_gates_met'])} "
        f"retro_stress_gate={int(stress_gate['all_numeric_gates_met'])} "
        "independent_oos=0 execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from .research_brent_v229_historical_v238e import (
    ARTIFACT_CONTRACT, BASE_SLIPPAGE_PIPS, BASE_SPREAD_PIPS,
    BROKER_SHADOW_REFERENCE, CHILD_LOT, CHILD_UNITS,
    COMMISSION_PIPS_ROUND_TRIP, CONTRACT_UNITS_PER_LOT,
    EXECUTION_AUTHORITY, EXECUTION_INFLUENCE, HISTDATA_PAIR,
    LIVE_EXECUTION_ENABLED, POLICY_EFFECT, RESEARCH_VERSION,
    STRESS_SLIPPAGE_MULTIPLIER, STRESS_SPREAD_MULTIPLIER,
    account_ledger, effective_trades, summarize_trades,
)

ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026_YTD": (2025, 2026),
}


def _shard_dir() -> Path:
    path = Path(os.getenv("BRENT_V238E_SHARD_DIR", "/tmp/brent-v238e-shards"))
    if not path.exists():
        raise SystemExit(f"BRENT_V238E_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(os.getenv(
        "BRENT_V238E_FULL_OUTPUT",
        "artifacts/brent-v229-historical-v238e-full.json",
    ))


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows = []
    for file in sorted(path.rglob("brent-v229-historical-v238e-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            rows.append(payload)
    rows.sort(key=lambda row: int(row["year"]))
    return rows


def _filter_cost(rows: Sequence[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [
        dict(row) for row in rows
        if str(row.get("cost_mode") or "").upper() == mode.upper()
    ]


def _breakdown(rows: Sequence[dict[str, Any]], key: str, values: Sequence[Any]):
    output = {}
    for value in values:
        selected = [
            dict(row) for row in rows
            if str(row.get(key) or "").upper() == str(value).upper()
        ]
        output[str(value)] = summarize_trades(selected)
    return output


def _era_reports(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for name, (start, end) in ERAS.items():
        selected = [
            dict(row) for row in rows
            if start <= int(row.get("year") or 0) <= end
        ]
        output[name] = {
            "years": [start, end],
            "summary": summarize_trades(selected),
            "slot_breakdown": _breakdown(selected, "slot", [1, 2, 3, 4]),
            "source_breakdown": _breakdown(
                selected, "candidate_source", ["H4", "H1", "M15"]
            ),
        }
    return output


def _account_scenarios(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "margin_only": account_ledger(
            rows, initial_balance=100.0, leverage=100.0,
            margin_cap_fraction=None,
        ),
        "margin_cap_50pct": account_ledger(
            rows, initial_balance=100.0, leverage=100.0,
            margin_cap_fraction=0.50,
        ),
    }


def _report(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": summarize_trades(rows),
        "slot_breakdown": _breakdown(rows, "slot", [1, 2, 3, 4]),
        "source_breakdown": _breakdown(
            rows, "candidate_source", ["H4", "H1", "M15"]
        ),
        "eras": _era_reports(rows),
        "account_100_usd_1_100": _account_scenarios(rows),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) != 15:
        raise SystemExit(f"BRENT_V238E_EXPECTED_15_SHARDS:{len(shards)}")

    plans, trades = [], []
    yearly = {}
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

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "instrument": "BRENT",
        "historical_pair": HISTDATA_PAIR,
        "broker_shadow_reference": BROKER_SHADOW_REFERENCE,
        "source_identity_evidence": "V238D_3_WINDOW_CONSENSUS",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "current_year_partial": bool(shards[-1].get("partial_current_year")),
        "parent_plan_count": len(plans),
        "raw_trade_record_count": len(trades),
        "parent_cancel_count": len(cancel_at),
        "method": {
            "strategy": "V229_STYLE_DEPTH_2_PRETOUCH_2_M5_CONFIRMATION",
            "engine_source": "V236_WITH_ISOLATED_BRENT_RESEARCH_ECONOMICS",
            "frozen_depth_prior": "XAU_V225_2",
            "brent_full_sample_depth_fit": False,
            "child_lot": CHILD_LOT,
            "contract_units_per_lot": CONTRACT_UNITS_PER_LOT,
            "child_units": CHILD_UNITS,
            "initial_capital_usd": 100.0,
            "leverage": 100.0,
            "base_costs": {
                "spread_pips": BASE_SPREAD_PIPS,
                "spread_usd": BASE_SPREAD_PIPS * 0.01,
                "slippage_pips": BASE_SLIPPAGE_PIPS,
                "slippage_usd": BASE_SLIPPAGE_PIPS * 0.01,
                "commission_pips_round_trip": COMMISSION_PIPS_ROUND_TRIP,
            },
            "stress_costs": {
                "spread_multiplier": STRESS_SPREAD_MULTIPLIER,
                "slippage_multiplier": STRESS_SLIPPAGE_MULTIPLIER,
            },
            "ambiguous_bar_policy": "STOP_FIRST",
        },
        "base": _report(base),
        "stress": _report(stress),
        "yearly": yearly,
        "limitations": [
            "Research-only historical simulation; no broker order authority.",
            "Frozen XAU V225.2 entry-depth priors; no Brent full-sample fitting.",
            "V238D source identity is validated on three 2025-2026 windows; pre-2024 broker continuity is not asserted.",
            "Current published BRENT spread is used as a historical proxy rather than reconstructed historical spreads.",
            "Base slippage is a conservative research assumption, not an observed historical fill series.",
            "2026 is partial through the available HistData endpoint.",
            "Account ledger uses realized balance and does not model broker stop-out on intratrade equity.",
        ],
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": False,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    base_cap = payload["base"]["account_100_usd_1_100"]["margin_cap_50pct"]
    stress_cap = payload["stress"]["account_100_usd_1_100"]["margin_cap_50pct"]
    print(
        "BRENT_V229_HISTORICAL_V238E_FULL "
        f"plans={len(plans)} completed={payload['base']['summary']['completed']} "
        f"pf={payload['base']['summary']['profit_factor_r']} "
        f"exp_r={payload['base']['summary']['expectancy_r']} "
        f"base_cap50={base_cap['ending_balance']:.2f} "
        f"stress_cap50={stress_cap['ending_balance']:.2f} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

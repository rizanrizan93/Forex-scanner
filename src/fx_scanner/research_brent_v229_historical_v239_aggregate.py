from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from .research_brent_v229_historical_v236 import (
    ARTIFACT_CONTRACT,
    CHILD_LOT,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    RESEARCH_VERSION,
    account_ledger,
    effective_trades,
    summarize_trades,
)

ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026_YTD": (2025, 2026),
}


def _shard_dir() -> Path:
    path = Path(os.getenv("BRENT_V239_SHARD_DIR", "/tmp/brent-v236-shards"))
    if not path.exists():
        raise SystemExit(f"BRENT_V239_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "BRENT_V239_FULL_OUTPUT",
            "artifacts/brent-v229-historical-v236-full.json",
        )
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for file in sorted(path.rglob("brent-v229-historical-v236-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            output.append(payload)
    output.sort(key=lambda row: int(row["year"]))
    return output


def _filter_cost(rows: Sequence[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("cost_mode") or "").upper() == str(mode).upper()
    ]


def _slot_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"L{slot}": summarize_trades(
            [
                dict(row)
                for row in rows
                if int(row.get("slot") or 0) == slot
            ]
        )
        for slot in range(1, 5)
    }


def _source_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for source in ("H4", "H1", "M15"):
        selected = [
            dict(row)
            for row in rows
            if str(row.get("candidate_source") or "").upper() == source
        ]
        output[source] = summarize_trades(selected)
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
            "summary": summarize_trades(selected),
            "slot_breakdown": _slot_breakdown(selected),
            "source_breakdown": _source_breakdown(selected),
        }
    return output


def _account_scenarios(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "margin_only": account_ledger(
            rows,
            initial_balance=100.0,
            leverage=100.0,
            margin_cap_fraction=None,
        ),
        "margin_cap_50pct": account_ledger(
            rows,
            initial_balance=100.0,
            leverage=100.0,
            margin_cap_fraction=0.50,
        ),
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) < 15:
        raise SystemExit(f"BRENT_V239_EXPECTED_15_SHARDS:{len(shards)}")

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

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "pair": "BCOUSD",
        "broker_reference_symbol": "BRENT",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "current_year_partial": bool(shards[-1].get("partial_current_year")),
        "current_year_data_end": dict(shards[-1].get("price_provenance") or {}).get("window_end"),
        "parent_plan_count": len(plans),
        "raw_trade_record_count": len(trades),
        "parent_cancel_count": len(cancel_at),
        "method": {
            "strategy": "V229_STYLE_DEPTH_2_PRETOUCH_2_M5_CONFIRMATION",
            "frozen_depth_prior": "XAU_V225_2",
            "brent_full_sample_depth_fit": False,
            "broker_contract_units_per_lot": 1000.0,
            "broker_average_spread_usd_sep_2026": 0.04,
            "child_lot": CHILD_LOT,
            "initial_capital_usd": 100.0,
            "leverage": 100.0,
            "base_costs": {
                "spread_pips": 4.0,
                "slippage_pips": 1.0,
                "commission_pips_round_trip": 0.0,
            },
            "stress_costs": {
                "spread_multiplier": 1.25,
                "slippage_multiplier": 1.50,
            },
            "ambiguous_bar_policy": "STOP_FIRST",
            "parent_supersession": "NEXT_VALID_PARENT_PLAN_CANCELS_UNFILLED_CHILDREN",
            "account_margin_model": (
                "balance-based closed-PnL ledger; open-position unrealized PnL is not "
                "used for admission. Margin-only and 50% margin-cap scenarios reported."
            ),
        },
        "base": {
            "summary": summarize_trades(base),
            "slot_breakdown": _slot_breakdown(base),
            "source_breakdown": _source_breakdown(base),
            "eras": _era_reports(base),
            "account_100_usd_1_100": _account_scenarios(base),
        },
        "stress": {
            "summary": summarize_trades(stress),
            "slot_breakdown": _slot_breakdown(stress),
            "source_breakdown": _source_breakdown(stress),
            "eras": _era_reports(stress),
            "account_100_usd_1_100": _account_scenarios(stress),
        },
        "yearly": yearly,
        "limitations": [
            (
                "V239 reconstructs the V229 child-entry and structural-target mechanics "
                "from causal H4 first-touch candidates; it does not replay every historical "
                "AFIC path-projection focus decision from the live atlas."
            ),
            (
                "The fixed XAU V225.2 depth prior is deliberately frozen to avoid fitting "
                "BRENT using future 2012-2026 information."
            ),
            (
                "2026 is year-to-date through the available HistData endpoint, not a full year."
            ),
            (
                "The account ledger uses realized balance for margin admission and does not "
                "simulate broker stop-out from intratrade mark-to-market equity."
            ),
            (
                "30-day research exit is applied only when neither structural TP nor SL occurs."
            ),
        ],
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    base_margin = payload["base"]["account_100_usd_1_100"]["margin_only"]
    base_cap = payload["base"]["account_100_usd_1_100"]["margin_cap_50pct"]
    stress_cap = payload["stress"]["account_100_usd_1_100"]["margin_cap_50pct"]
    print(
        "BRENT_V229_HISTORICAL_V239_FULL "
        f"plans={len(plans)} "
        f"base_completed={payload['base']['summary']['completed']} "
        f"base_pf={payload['base']['summary']['profit_factor_r']} "
        f"base_exp_r={payload['base']['summary']['expectancy_r']} "
        f"balance_margin_only={base_margin['ending_balance']:.2f} "
        f"balance_cap50={base_cap['ending_balance']:.2f} "
        f"stress_cap50={stress_cap['ending_balance']:.2f} "
        f"partial_2026={int(payload['current_year_partial'])} execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

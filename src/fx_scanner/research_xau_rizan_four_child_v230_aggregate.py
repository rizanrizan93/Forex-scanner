from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .research_xau_rizan_four_child_v230 import (
    ARTIFACT_CONTRACT,
    ERAS,
    RESEARCH_VERSION,
    summarize_group,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "research_xau_rizan_four_child_v230"
STARTING_BALANCE_USD = 200.0
ASSUMED_LEVERAGE = "1:100"


def _load_shards(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file in sorted(path.rglob("xau-rizan-four-child-v230-*.json")):
        payload = json.loads(file.read_text())
        if payload.get("year") is not None:
            rows.append(payload)
    rows.sort(key=lambda x: int(x["year"]))
    return rows


def _equity_path(children: list[dict[str, Any]], *, cost_per_fill: float) -> dict[str, Any]:
    closed = [
        dict(row) for row in children
        if row.get("filled_at") and row.get("pnl_usd_001") is not None
    ]
    closed.sort(key=lambda row: str(row.get("exit_at") or ""))
    balance = STARTING_BALANCE_USD
    peak = balance
    max_dd = 0.0
    min_balance = balance
    negative_balance_at = None
    for row in closed:
        balance += float(row.get("pnl_usd_001") or 0.0) - float(cost_per_fill)
        peak = max(peak, balance)
        min_balance = min(min_balance, balance)
        max_dd = max(max_dd, peak - balance)
        if balance <= 0 and negative_balance_at is None:
            negative_balance_at = row.get("exit_at")
    return {
        "starting_balance_usd": STARTING_BALANCE_USD,
        "ending_balance_usd": balance,
        "net_profit_usd": balance - STARTING_BALANCE_USD,
        "max_drawdown_usd_realized_sequence": max_dd,
        "min_balance_usd": min_balance,
        "balance_nonpositive_at": negative_balance_at,
        "round_trip_cost_usd_per_filled_child": float(cost_per_fill),
        "leverage_label": ASSUMED_LEVERAGE,
        "margin_liquidation_modelled": False,
        "portfolio_overlap_margin_modelled": False,
    }


def run() -> int:
    shard_dir = Path(os.getenv("XAU_V230_SHARD_DIR", "/tmp/v230-shards"))
    shards = _load_shards(shard_dir)
    if not shards:
        raise SystemExit("XAU_V230_NO_SHARDS")

    parents = [dict(row) for shard in shards for row in list(shard.get("parents") or [])]
    children = [dict(row) for shard in shards for row in list(shard.get("children") or [])]
    overall = summarize_group(children, parents)
    yearly = {
        str(int(shard["year"])): dict(shard.get("summary") or {})
        for shard in shards
    }
    eras: dict[str, Any] = {}
    for name, (start, end) in ERAS.items():
        era_parents = [row for row in parents if start <= int(row.get("year") or 0) <= end]
        era_children = [row for row in children if start <= int(row.get("year") or 0) <= end]
        eras[name] = {
            "years": [start, end],
            "summary": summarize_group(era_children, era_parents),
        }

    capital_scenarios = {
        str(cost): _equity_path(children, cost_per_fill=cost)
        for cost in (0.0, 0.30, 0.50, 1.00)
    }
    observed_at = datetime.now(tz=UTC)
    output = Path(
        os.getenv(
            "XAU_V230_FULL_OUTPUT",
            "artifacts/xau-rizan-four-child-v230-full.json",
        )
    )
    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "contains_secrets": False,
        "observed_at": observed_at.isoformat(),
        "years": [int(shard["year"]) for shard in shards],
        "year_count": len(shards),
        "prior_mode": "FROZEN_FULL_2012_2026_RETROSPECTIVE",
        "prior_warning": (
            "Entry-depth priors are the final V225.2 2012-2026 frozen estimates. "
            "Therefore V230 is an exact retrospective replay of the current strategy, "
            "not a walk-forward out-of-sample estimate. Entry selection, M5 confirmation, "
            "fills and exits remain causal within each replay year."
        ),
        "overall": overall,
        "eras": eras,
        "yearly": yearly,
        "capital_scenarios": capital_scenarios,
        "capital_model": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "leverage_label": ASSUMED_LEVERAGE,
            "fixed_child_lot": 0.01,
            "assumed_oz_per_001_lot": 1.0,
            "margin_liquidation_modelled": False,
            "account_position_cap_modelled": False,
            "note": (
                "Balance scenarios add realized child PnL in exit order. They do not yet "
                "simulate broker margin, stop-out, overlapping-position capacity or "
                "variable historical spread. Cost sensitivity is reported separately."
            ),
        },
        "same_bar_precedence": "STOP_FIRST",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    healthy = len(shards) >= 15
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=healthy,
            lag_seconds=0.0,
            details={
                "contract": payload["artifact_contract"],
                "research_version": RESEARCH_VERSION,
                "year_count": len(shards),
                "years": payload["years"],
                "prior_mode": payload["prior_mode"],
                "overall": overall,
                "eras": eras,
                "capital_scenarios": capital_scenarios,
                "same_bar_precedence": payload["same_bar_precedence"],
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
                "artifact_path": str(output),
                "observed_at": observed_at.isoformat(),
                "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            },
        )
    except Exception as exc:
        print(f"V230_HEARTBEAT_WRITE_WARNING:{type(exc).__name__}:{exc}")

    print(
        "XAU_RIZAN_FOUR_CHILD_V230_FULL "
        f"years={len(shards)} parents={overall['parents']} "
        f"filled={overall['children_filled']} tp={overall['tp']} sl={overall['sl']} "
        f"pnl={overall['gross_pnl_usd_001']:.4f} "
        f"balance200={capital_scenarios['0.0']['ending_balance_usd']:.4f} "
        "execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

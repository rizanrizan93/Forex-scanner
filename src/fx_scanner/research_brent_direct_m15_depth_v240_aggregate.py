from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

from .research_brent_direct_m15_depth_v240 import (
    ARTIFACT_CONTRACT,
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    DEPTH_VARIANTS,
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    MAX_POSITIONS,
    POLICY_EFFECT,
    PRIMARY_VARIANT,
    PROMOTION_AUTHORITY,
    RESEARCH_VERSION,
    STOP_BUFFER_ATR,
    TARGET_ATR_MULTIPLE,
    account_ledger,
    summarize_trades,
)

ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026_YTD": (2025, 2026),
}


def _shard_dir() -> Path:
    path = Path(os.getenv("BRENT_V240_SHARD_DIR", "/tmp/brent-v240-shards"))
    if not path.exists():
        raise SystemExit(f"BRENT_V240_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _output_path() -> Path:
    return Path(
        os.getenv(
            "BRENT_V240_FULL_OUTPUT",
            "artifacts/brent-direct-m15-v240-full.json",
        )
    )


def _load_shards(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for file in sorted(path.rglob("brent-direct-m15-v240-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            output.append(payload)
    output.sort(key=lambda row: int(row["year"]))
    return output


def _select(
    rows: Sequence[dict[str, Any]],
    *,
    variant: str,
    cost_mode: str,
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if str(row.get("variant") or "") == variant
        and str(row.get("cost_mode") or "").upper() == cost_mode.upper()
    ]


def _direction_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        direction: summarize_trades(
            [
                dict(row)
                for row in rows
                if str(row.get("direction") or "").upper() == direction
            ]
        )
        for direction in ("LONG", "SHORT")
    }


def _era_breakdown(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
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
            "direction_breakdown": _direction_breakdown(selected),
        }
    return output


def _positive(summary: dict[str, Any]) -> bool:
    pf = summary.get("profit_factor_r")
    exp = summary.get("expectancy_r")
    completed = int(summary.get("completed") or 0)
    return bool(
        completed >= 100
        and pf is not None
        and float(pf) > 1.0
        and exp is not None
        and float(exp) > 0.0
    )


def run() -> int:
    shards = _load_shards(_shard_dir())
    if len(shards) < 15:
        raise SystemExit(f"BRENT_V240_EXPECTED_15_SHARDS:{len(shards)}")

    trades: list[dict[str, Any]] = []
    yearly: dict[str, Any] = {}
    for shard in shards:
        year = int(shard["year"])
        trades.extend(dict(row) for row in list(shard.get("trades") or []))
        yearly[str(year)] = {
            "partial_current_year": bool(shard.get("partial_current_year")),
            "episodes": int(shard.get("m15_episode_count") or 0),
            "trade_records": int(shard.get("trade_record_count") or 0),
        }

    variants: dict[str, Any] = {}
    for variant, depth in DEPTH_VARIANTS.items():
        base = _select(trades, variant=variant, cost_mode="BASE")
        stress = _select(trades, variant=variant, cost_mode="STRESS")
        variants[variant] = {
            "depth": float(depth),
            "base": {
                "summary": summarize_trades(base),
                "direction_breakdown": _direction_breakdown(base),
                "eras": _era_breakdown(base),
            },
            "stress": {
                "summary": summarize_trades(stress),
                "direction_breakdown": _direction_breakdown(stress),
                "eras": _era_breakdown(stress),
            },
        }

    primary_base = _select(trades, variant=PRIMARY_VARIANT, cost_mode="BASE")
    primary_stress = _select(trades, variant=PRIMARY_VARIANT, cost_mode="STRESS")
    primary = variants[PRIMARY_VARIANT]
    primary_era_positive = {
        era: _positive(dict(report["summary"]))
        for era, report in dict(primary["base"]["eras"]).items()
    }
    primary_stress_era_positive = {
        era: _positive(dict(report["summary"]))
        for era, report in dict(primary["stress"]["eras"]).items()
    }
    sensitivity_positive = {
        variant: _positive(dict(report["base"]["summary"]))
        for variant, report in variants.items()
    }
    sensitivity_era_positive = {
        variant: {
            era: _positive(dict(era_report["summary"]))
            for era, era_report in dict(report["base"]["eras"]).items()
        }
        for variant, report in variants.items()
    }
    research_gate = {
        "primary_base_positive": _positive(dict(primary["base"]["summary"])),
        "primary_stress_positive": _positive(dict(primary["stress"]["summary"])),
        "primary_all_eras_positive": all(primary_era_positive.values()),
        "primary_era_positive": primary_era_positive,
        "primary_stress_all_eras_positive": all(primary_stress_era_positive.values()),
        "primary_stress_era_positive": primary_stress_era_positive,
        "all_depth_sensitivity_base_positive": all(sensitivity_positive.values()),
        "sensitivity_positive": sensitivity_positive,
        "all_depth_sensitivity_all_eras_positive": all(
            all(values.values()) for values in sensitivity_era_positive.values()
        ),
        "sensitivity_era_positive": sensitivity_era_positive,
    }
    research_gate["passes_all"] = all(
        [
            research_gate["primary_base_positive"],
            research_gate["primary_stress_positive"],
            research_gate["primary_all_eras_positive"],
            research_gate["primary_stress_all_eras_positive"],
            research_gate["all_depth_sensitivity_base_positive"],
            research_gate["all_depth_sensitivity_all_eras_positive"],
        ]
    )

    payload = {
        "artifact_contract": f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
        "research_version": RESEARCH_VERSION,
        "pair": "BCOUSD",
        "broker_reference_symbol": "BRENT",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "current_year_partial": bool(shards[-1].get("partial_current_year")),
        "episode_count": sum(int(row.get("m15_episode_count") or 0) for row in shards),
        "method": {
            "strategy": "DIRECT_M15_FIRST_TOUCH_UNI_DEPTH",
            "primary_depth": DEPTH_VARIANTS[PRIMARY_VARIANT],
            "sensitivity_depths": DEPTH_VARIANTS,
            "target_atr_multiple": TARGET_ATR_MULTIPLE,
            "stop_buffer_atr": STOP_BUFFER_ATR,
            "max_position_minutes": 240,
            "first_touch_only": True,
            "pending_cancel": "V225_FIRST_TOUCH_OUTCOME_AT",
            "ambiguous_bar_policy": "STOP_FIRST",
            "base_costs": {
                "spread_pips": BASE_SPREAD_PIPS,
                "slippage_pips": BASE_SLIPPAGE_PIPS,
                "commission_pips_round_trip": 0.0,
            },
            "stress_costs": {
                "spread_multiplier": 1.25,
                "slippage_multiplier": 1.50,
            },
            "child_lot": 0.01,
            "contract_units_per_lot": 1000.0,
            "initial_capital_usd": 100.0,
            "leverage": 100.0,
            "max_positions": MAX_POSITIONS,
        },
        "variants": variants,
        "primary_account_100_usd_1_100": {
            "base_margin_only": account_ledger(
                primary_base,
                initial_balance=100.0,
                leverage=100.0,
                margin_cap_fraction=None,
                max_positions=MAX_POSITIONS,
            ),
            "base_margin_cap_50pct": account_ledger(
                primary_base,
                initial_balance=100.0,
                leverage=100.0,
                margin_cap_fraction=0.50,
                max_positions=MAX_POSITIONS,
            ),
            "stress_margin_cap_50pct": account_ledger(
                primary_stress,
                initial_balance=100.0,
                leverage=100.0,
                margin_cap_fraction=0.50,
                max_positions=MAX_POSITIONS,
            ),
        },
        "research_gate": research_gate,
        "yearly": yearly,
        "limitations": [
            (
                "The primary depth of 10% was fixed before V240 execution testing. "
                "D05 and D15 are perturbation checks, not post-hoc alternatives."
            ),
            (
                "Historical source identity is supported by V238D as a current "
                "SHADOW_REFERENCE to FP Markets BRENT; it is not proof that the "
                "entire 2012-2026 HistData series is the same broker contract."
            ),
            (
                "The account ledger uses realized balance for admission and does not "
                "model broker stop-out from intratrade mark-to-market equity."
            ),
            (
                "A passing research gate still does not grant DEMO or LIVE execution authority."
            ),
        ],
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
    }

    output = _output_path()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")

    primary_summary = payload["variants"][PRIMARY_VARIANT]["base"]["summary"]
    stress_summary = payload["variants"][PRIMARY_VARIANT]["stress"]["summary"]
    account = payload["primary_account_100_usd_1_100"]["base_margin_cap_50pct"]
    print(
        "BRENT_DIRECT_M15_V240_FULL "
        f"episodes={payload['episode_count']} "
        f"completed={primary_summary['completed']} "
        f"pf={primary_summary['profit_factor_r']} "
        f"exp_r={primary_summary['expectancy_r']} "
        f"stress_pf={stress_summary['profit_factor_r']} "
        f"balance_cap50={account['ending_balance']:.2f} "
        f"research_gate={int(payload['research_gate']['passes_all'])} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

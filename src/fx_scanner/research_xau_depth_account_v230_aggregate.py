from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ensure_utc

RESEARCH_VERSION = "XAU_DEPTH_ACCOUNT_REPLAY_V230_1"
ARTIFACT_CONTRACT = "XAU_DEPTH_ACCOUNT_REPLAY_V230_FULL_1"

INITIAL_BALANCE = 200.0
MAX_CONCURRENT_ORDERS = 2
FRICTION_SCENARIOS = (0.0, 0.5)


def _dt(value: Any) -> datetime:
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _era(year: int) -> str:
    if year <= 2018:
        return "2012_2018"
    if year <= 2024:
        return "2019_2024"
    return "2025_2026"


def _load_orders(root: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = sorted(glob.glob(os.path.join(root, "**", "xau-depth-account-v230-*.json"), recursive=True))
    if not files:
        raise RuntimeError("V230_NO_YEAR_ARTIFACTS")
    orders: list[dict[str, Any]] = []
    years: list[int] = []
    diagnostics: dict[str, int] = {}
    for path in files:
        payload = json.loads(Path(path).read_text())
        if str(payload.get("research_version") or "") != RESEARCH_VERSION:
            raise RuntimeError(f"V230_VERSION_MISMATCH:{path}")
        year = int(payload["year"])
        years.append(year)
        orders.extend(dict(row) for row in list(payload.get("orders") or []))
        for key, value in dict(payload.get("diagnostics") or {}).items():
            diagnostics[key] = diagnostics.get(key, 0) + int(value or 0)
    orders.sort(key=lambda row: (_dt(row["fill_at"]), str(row.get("candidate_key") or ""), str(row.get("slot") or "")))
    return orders, {
        "files": len(files),
        "years": sorted(set(years)),
        "diagnostics": diagnostics,
    }


def simulate_account(
    orders: list[dict[str, Any]],
    *,
    initial_balance: float,
    friction_points: float,
) -> dict[str, Any]:
    balance = float(initial_balance)
    peak_balance = balance
    max_drawdown = 0.0
    active: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    skipped_position_cap = 0
    skipped_margin = 0
    min_balance = balance

    def realize_until(point: datetime) -> None:
        nonlocal balance, peak_balance, max_drawdown, active, min_balance
        keep: list[dict[str, Any]] = []
        closing = sorted(
            [row for row in active if _dt(row["exit_at"]) <= point],
            key=lambda row: _dt(row["exit_at"]),
        )
        for row in closing:
            pnl = float(row["gross_pnl_usd"]) - float(friction_points)
            balance += pnl
            peak_balance = max(peak_balance, balance)
            min_balance = min(min_balance, balance)
            if peak_balance > 0:
                max_drawdown = max(max_drawdown, (peak_balance - balance) / peak_balance)
        closing_ids = {id(row) for row in closing}
        for row in active:
            if id(row) not in closing_ids:
                keep.append(row)
        active = keep

    for raw in orders:
        row = dict(raw)
        fill_at = _dt(row["fill_at"])
        realize_until(fill_at)

        if balance <= 0:
            skipped_margin += 1
            continue
        if len(active) >= MAX_CONCURRENT_ORDERS:
            skipped_position_cap += 1
            continue

        margin = float(row.get("margin_usd_1_to_100") or 0.0)
        used_margin = sum(float(item.get("margin_usd_1_to_100") or 0.0) for item in active)
        # No risk-per-trade constraint. Only broker-style capital sufficiency
        # remains: fixed 0.01 lot order must fit under 1:100 margin.
        if margin <= 0 or used_margin + margin > balance:
            skipped_margin += 1
            continue

        row["net_pnl_usd"] = float(row["gross_pnl_usd"]) - float(friction_points)
        active.append(row)
        executed.append(row)

    realize_until(datetime.max.replace(tzinfo=_dt("2026-01-01T00:00:00+00:00").tzinfo))

    wins = sum(float(row["net_pnl_usd"]) > 0 for row in executed)
    losses = sum(float(row["net_pnl_usd"]) < 0 for row in executed)
    flats = len(executed) - wins - losses
    gross_profit = sum(max(float(row["net_pnl_usd"]), 0.0) for row in executed)
    gross_loss = -sum(min(float(row["net_pnl_usd"]), 0.0) for row in executed)
    tp_count = sum(str(row.get("exit_reason") or "") == "TP" for row in executed)
    sl_count = sum(str(row.get("exit_reason") or "").startswith("SL") for row in executed)
    time_count = sum(str(row.get("exit_reason") or "").startswith("TIME_EXIT") for row in executed)
    source_mix: dict[str, int] = {}
    target_mix: dict[str, int] = {}
    slot_mix: dict[str, int] = {}
    for row in executed:
        source = str(row.get("source_layer") or "UNKNOWN")
        source_mix[source] = source_mix.get(source, 0) + 1
        target = str(row.get("target_source") or "UNKNOWN")
        target_mix[target] = target_mix.get(target, 0) + 1
        slot = str(row.get("slot") or "UNKNOWN")
        slot_mix[slot] = slot_mix.get(slot, 0) + 1

    return {
        "initial_balance": initial_balance,
        "final_balance": balance,
        "net_profit": balance - initial_balance,
        "return_pct": (balance / initial_balance - 1.0) * 100.0 if initial_balance else None,
        "executed_orders": len(executed),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": wins / (wins + losses) if wins + losses else None,
        "tp_count": tp_count,
        "sl_count": sl_count,
        "time_exit_count": time_count,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_realized_drawdown": max_drawdown,
        "min_realized_balance": min_balance,
        "skipped_position_cap": skipped_position_cap,
        "skipped_margin": skipped_margin,
        "friction_points_per_order": friction_points,
        "source_mix": source_mix,
        "target_mix": target_mix,
        "slot_mix": slot_mix,
    }


def aggregate(root: str) -> dict[str, Any]:
    orders, meta = _load_orders(root)
    expected_years = list(range(2012, 2027))
    if meta["years"] != expected_years:
        raise RuntimeError(f"V230_YEAR_COVERAGE_INVALID:{meta['years']}")

    scenarios: dict[str, Any] = {}
    for friction in FRICTION_SCENARIOS:
        key = f"friction_{str(friction).replace('.', '_')}"
        scenarios[key] = {
            "continuous_2012_2026": simulate_account(
                orders,
                initial_balance=INITIAL_BALANCE,
                friction_points=friction,
            ),
            "eras_reset_200": {
                era: simulate_account(
                    [row for row in orders if _era(int(row["year"])) == era],
                    initial_balance=INITIAL_BALANCE,
                    friction_points=friction,
                )
                for era in ("2012_2018", "2019_2024", "2025_2026")
            },
        }

    year_stats: dict[str, Any] = {}
    for year in range(2012, 2027):
        subset = [row for row in orders if int(row["year"]) == year]
        year_stats[str(year)] = {
            "candidate_orders": len(subset),
            "gross_tp": sum(str(row.get("exit_reason") or "") == "TP" for row in subset),
            "gross_sl": sum(str(row.get("exit_reason") or "").startswith("SL") for row in subset),
            "gross_time_exit": sum(str(row.get("exit_reason") or "").startswith("TIME_EXIT") for row in subset),
            "mean_rr": (
                sum(float(row.get("rr") or 0.0) for row in subset) / len(subset)
                if subset else None
            ),
        }

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "initial_balance": INITIAL_BALANCE,
        "leverage": "1:100",
        "fixed_lot_per_order": 0.01,
        "max_concurrent_orders": MAX_CONCURRENT_ORDERS,
        "risk_percent_filter": None,
        "rr_gate": 1.0,
        "year_coverage": meta["years"],
        "candidate_order_count": len(orders),
        "generation_diagnostics": meta["diagnostics"],
        "scenarios": scenarios,
        "year_stats": year_stats,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "No risk-per-trade cap or risk-based sizing is used. Every eligible "
            "candidate order is fixed at 0.01 lot, up to two concurrent positions. "
            "The only capital constraint is 1:100 margin sufficiency. Drawdown is "
            "realized-balance drawdown, not intratrade equity drawdown."
        ),
    }


def run() -> int:
    root = os.environ.get("XAU_V230_SHARD_DIR", "/tmp/v230-shards")
    output = os.environ.get(
        "XAU_V230_FULL_OUTPUT",
        "artifacts/xau-depth-account-v230-full.json",
    )
    result = aggregate(root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(
        "XAU_V230_FULL "
        f"orders={result['candidate_order_count']} "
        f"gross_final={result['scenarios']['friction_0_0']['continuous_2012_2026']['final_balance']:.2f} "
        f"stress_final={result['scenarios']['friction_0_5']['continuous_2012_2026']['final_balance']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

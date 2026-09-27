from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

INITIAL_BALANCE = 100.0
LEVERAGE = 100
MARGIN_CAP = 0.50
MAX_OPEN_POSITIONS = 10

ERAS = {
    "2012_2018": (2012, 2018),
    "2019_2024": (2019, 2024),
    "2025_2026": (2025, 2026),
}


def _dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _shard_dir() -> Path:
    path = Path(os.getenv("EURUSD_V236_SHARD_DIR", "/tmp/eurusd-v236-shards").strip())
    if not path.exists():
        raise SystemExit(f"EURUSD_V236_SHARD_DIR_NOT_FOUND:{path}")
    return path


def _load_shards(path: Path) -> list[dict[str, Any]]:
    out = []
    for file in sorted(path.rglob("eurusd-v229-v236-*.json")):
        payload = json.loads(file.read_text())
        if "year" in payload:
            out.append(payload)
    out.sort(key=lambda row: int(row["year"]))
    return out


def _records(
    shards: Iterable[dict[str, Any]],
    *,
    variant: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict[str, Any]]:
    out = []
    for shard in shards:
        year = int(shard["year"])
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        node = dict(dict(shard.get("variants") or {}).get(variant) or {})
        for raw in list(node.get("child_records") or []):
            row = dict(raw)
            if row.get("status") != "CLOSED" or not row.get("fill_at") or not row.get("exit_at"):
                continue
            row["year"] = year
            row["variant"] = variant
            out.append(row)
    return out


def replay_account(
    rows: Iterable[dict[str, Any]],
    *,
    initial_balance: float = INITIAL_BALANCE,
    leverage: int = LEVERAGE,
    margin_cap: float | None = MARGIN_CAP,
    max_open_positions: int = MAX_OPEN_POSITIONS,
) -> dict[str, Any]:
    records = [dict(row) for row in rows]
    events: list[tuple[datetime, int, str, dict[str, Any]]] = []
    for i, row in enumerate(records):
        key = f"{row.get('year')}:{row.get('parent_id')}:{row.get('slot')}:{i}"
        row["_key"] = key
        events.append((_dt(row["fill_at"]), 0, "FILL", row))
        events.append((_dt(row["exit_at"]), 1, "EXIT", row))
    events.sort(key=lambda item: (item[0], item[1], item[3]["_key"]))

    balance = float(initial_balance)
    peak = balance
    max_dd = 0.0
    used_margin = 0.0
    max_margin_ratio = 0.0
    open_positions: dict[str, dict[str, Any]] = {}
    accepted: set[str] = set()
    closed: list[dict[str, Any]] = []
    blocked_margin = 0
    blocked_position_cap = 0
    blocked_bankrupt = 0
    bankrupt_at = None
    current_losing_streak = 0
    max_losing_streak = 0

    for at, _, kind, row in events:
        key = str(row["_key"])
        if kind == "FILL":
            if key in accepted:
                continue
            if balance <= 0:
                blocked_bankrupt += 1
                if bankrupt_at is None:
                    bankrupt_at = at.isoformat()
                continue
            if len(open_positions) >= int(max_open_positions):
                blocked_position_cap += 1
                continue
            margin = float(row.get("margin_required_1_100") or 0.0) * 100.0 / float(leverage)
            if margin_cap is not None:
                allowed = max(0.0, balance * float(margin_cap))
                if used_margin + margin > allowed + 1e-12:
                    blocked_margin += 1
                    continue
            accepted.add(key)
            open_positions[key] = row
            used_margin += margin
            ratio = 0.0 if balance <= 0 else used_margin / balance
            max_margin_ratio = max(max_margin_ratio, ratio)
            continue

        if key not in accepted or key not in open_positions:
            continue
        position = open_positions.pop(key)
        margin = float(position.get("margin_required_1_100") or 0.0) * 100.0 / float(leverage)
        used_margin = max(0.0, used_margin - margin)
        pnl = float(position.get("net_pnl") or 0.0)
        balance += pnl
        closed.append(position)
        peak = max(peak, balance)
        if peak > 0:
            max_dd = max(max_dd, (peak - balance) / peak)
        if pnl < 0:
            current_losing_streak += 1
            max_losing_streak = max(max_losing_streak, current_losing_streak)
        else:
            current_losing_streak = 0
        if balance <= 0 and bankrupt_at is None:
            bankrupt_at = at.isoformat()

    wins = [row for row in closed if float(row.get("net_pnl") or 0.0) > 0]
    losses = [row for row in closed if float(row.get("net_pnl") or 0.0) < 0]
    gross_profit = sum(float(row["net_pnl"]) for row in wins)
    gross_loss = abs(sum(float(row["net_pnl"]) for row in losses))
    net_r_values = [
        float(row["net_r"])
        for row in closed
        if row.get("net_r") is not None
    ]
    parents = {str(row.get("parent_id") or "") for row in closed if row.get("parent_id")}
    return {
        "initial_balance": float(initial_balance),
        "final_balance": float(balance),
        "net_profit": float(balance - initial_balance),
        "return_pct": float((balance / initial_balance - 1.0) * 100.0),
        "closed_children": len(closed),
        "parents_traded": len(parents),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": None if not closed else len(wins) / len(closed),
        "profit_factor": None if gross_loss <= 0 else gross_profit / gross_loss,
        "expectancy_usd_per_child": None if not closed else (balance - initial_balance) / len(closed),
        "expectancy_r_per_child": None if not net_r_values else sum(net_r_values) / len(net_r_values),
        "max_closed_balance_drawdown_pct": float(max_dd * 100.0),
        "max_consecutive_losses": int(max_losing_streak),
        "max_used_margin_to_balance_pct": float(max_margin_ratio * 100.0),
        "blocked_by_margin_cap": int(blocked_margin),
        "blocked_by_position_cap": int(blocked_position_cap),
        "blocked_after_bankruptcy": int(blocked_bankrupt),
        "bankrupt_at": bankrupt_at,
        "open_positions_at_end": len(open_positions),
        "leverage": int(leverage),
        "margin_cap_pct": None if margin_cap is None else float(margin_cap * 100.0),
        "max_open_positions": int(max_open_positions),
    }


def _variant_summary(shards: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    all_rows = _records(shards, variant=variant)
    primary = replay_account(all_rows)
    uncapped = replay_account(all_rows, margin_cap=None)
    eras = {}
    for name, (start, end) in ERAS.items():
        rows = _records(shards, variant=variant, start_year=start, end_year=end)
        eras[name] = {
            "years": [start, end],
            "record_count": len(rows),
            "account_reset_100_margin_cap_50": replay_account(rows),
            "account_reset_100_no_margin_cap": replay_account(rows, margin_cap=None),
        }
    return {
        "record_count": len(all_rows),
        "continuous_2012_2026_margin_cap_50": primary,
        "continuous_2012_2026_no_margin_cap": uncapped,
        "eras": eras,
    }


def run() -> int:
    shards = _load_shards(_shard_dir())
    if not shards:
        raise SystemExit("EURUSD_V236_NO_SHARDS")

    variants = {
        "current_literal": _variant_summary(shards, "current_literal"),
        "current_healthy": _variant_summary(shards, "current_healthy"),
        "seed_healthy": _variant_summary(shards, "seed_healthy"),
    }
    strict_oos_rows = _records(
        shards,
        variant="seed_healthy",
        start_year=2019,
        end_year=2026,
    )
    strict_oos = {
        "years": [2019, 2026],
        "prior_frozen_from": [2012, 2018],
        "record_count": len(strict_oos_rows),
        "account_reset_100_margin_cap_50": replay_account(strict_oos_rows),
        "account_reset_100_no_margin_cap": replay_account(strict_oos_rows, margin_cap=None),
    }
    yearly = {}
    for shard in shards:
        year = str(shard["year"])
        yearly[year] = {
            name: {
                "plan_count": dict(dict(shard.get("variants") or {}).get(name) or {}).get("plan_count"),
                "closed_children": dict(dict(shard.get("variants") or {}).get(name) or {}).get("closed_children"),
                "missed_children": dict(dict(shard.get("variants") or {}).get(name) or {}).get("missed_children"),
            }
            for name in ("current_literal", "current_healthy", "seed_healthy")
        }

    payload = {
        "artifact_contract": "EURUSD_V229_EXECUTION_BACKTEST_V236_1_FULL_2012_2026_1",
        "pair": "EURUSD",
        "years": [int(row["year"]) for row in shards],
        "year_count": len(shards),
        "capital_contract": {
            "initial_balance_usd": INITIAL_BALANCE,
            "leverage": f"1:{LEVERAGE}",
            "child_lot": 0.01,
            "maximum_children_per_parent": 4,
            "primary_margin_cap_pct": MARGIN_CAP * 100.0,
            "maximum_open_positions": MAX_OPEN_POSITIONS,
            "margin_guard_basis": "REALIZED_BALANCE_NOT_FLOATING_EQUITY",
        },
        "cost_contract": {
            "spread_pips": 0.8,
            "slippage_pips": 0.2,
            "commission_pips_round_trip": 0.2,
            "swap_pips_per_day": 0.0,
            "ambiguous_intrabar_policy": "STOP_FIRST",
        },
        "variants": variants,
        "strict_oos_2019_2026": strict_oos,
        "yearly": yearly,
        "interpretation": {
            "current_literal": (
                "Current full-history EURUSD depth prior replay. Parent is armed at the first "
                "eligible completed M15 after H4 zone availability; this exposes premature "
                "16-hour TTL failure if the current runtime can arm a distant zone too early."
            ),
            "current_healthy": (
                "Current full-history prior replay with a causal one-H4-ATR arming gate. "
                "This is the intended healthy V229-style operational replay, but the prior "
                "uses 2012-2026 EURUSD evidence and is therefore not strict OOS."
            ),
            "seed_healthy": (
                "Healthy arming with the EURUSD depth prior frozen from 2012-2018. "
                "Only 2019-2026 is treated as strict temporal OOS."
            ),
            "account": (
                "Primary account replay begins at $100 with 1:100 leverage, fixed 0.01 lot "
                "per accepted child, maximum four children per parent, 50% balance-based "
                "margin guard and 10-position cap. No automatic LIVE authority is created."
            ),
        },
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
    }

    output = Path(
        os.getenv(
            "EURUSD_V236_FULL_OUTPUT",
            "artifacts/eurusd-v229-v236-full.json",
        ).strip()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    healthy = variants["current_healthy"]["continuous_2012_2026_margin_cap_50"]
    oos = strict_oos["account_reset_100_margin_cap_50"]
    literal = variants["current_literal"]["continuous_2012_2026_margin_cap_50"]
    print(
        "EURUSD_V229_V236_FULL "
        f"years={len(shards)} "
        f"healthy_final={healthy['final_balance']:.2f} "
        f"literal_final={literal['final_balance']:.2f} "
        f"oos2019_final={oos['final_balance']:.2f} "
        f"healthy_pf={healthy['profit_factor']} "
        f"healthy_dd={healthy['max_closed_balance_drawdown_pct']:.2f} "
        "execution_authority=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

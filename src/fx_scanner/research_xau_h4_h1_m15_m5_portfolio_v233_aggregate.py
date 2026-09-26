from __future__ import annotations

import glob
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

CONT_VERSION = "XAU_H4_H1_M15_M5_CONTINUATION_V233_1"
V230_VERSION = "XAU_DEPTH_ACCOUNT_REPLAY_V230_1"
RESEARCH_VERSION = "XAU_H4_H1_M15_M5_PORTFOLIO_V233_1"
ARTIFACT_CONTRACT = "XAU_H4_H1_M15_M5_PORTFOLIO_V233_FULL_1"

INITIAL_BALANCE = 200.0
MAX_CONCURRENT = 2
MAX_LOT = 0.50
LOT_STEP = 0.01
FRICTIONS = (0.0, 0.5, 1.0)
MARGIN_FRACTIONS = (0.25, 0.50, 0.75, 0.95)
MIN_TRAIN_TRADES = 100
MIN_TRAIN_POSITIVE_YEARS = 4
MIN_TRAIN_PF = 1.05

NESTED_SOURCES = {"H1_NESTED_LOCATOR", "M15_NESTED_LOCATOR"}
TERMINAL_TARGET = "ATLAS_TERMINAL_OPPOSING_ZONE"


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _load_continuation(root: str) -> list[dict[str, Any]]:
    files = sorted(
        glob.glob(
            os.path.join(root, "**", "xau-h4-h1-m15-m5-continuation-v233-*.json"),
            recursive=True,
        )
    )
    if not files:
        raise RuntimeError("V233_CONTINUATION_SHARDS_MISSING")
    rows: list[dict[str, Any]] = []
    years: list[int] = []
    for path in files:
        payload = json.loads(Path(path).read_text())
        if payload.get("research_version") != CONT_VERSION:
            raise RuntimeError(f"V233_CONT_VERSION_MISMATCH:{path}")
        year = int(payload["year"])
        years.append(year)
        for raw in list(payload.get("trades") or []):
            row = dict(raw)
            row["engine"] = "CONTINUATION"
            row["trade_key"] = "|".join(
                (
                    "CONT",
                    str(row.get("variant_id") or ""),
                    str(row.get("direction") or ""),
                    str(row.get("fill_at") or ""),
                )
            )
            rows.append(row)
    observed = sorted(set(years))
    expected = list(range(2012, 2027))
    if observed != expected:
        raise RuntimeError(f"V233_CONT_YEAR_COVERAGE_INVALID:{observed}")
    rows.sort(key=lambda row: (_dt(row["fill_at"]), row["trade_key"]))
    return rows


def _load_v231_reversal(root: str) -> list[dict[str, Any]]:
    files = sorted(
        glob.glob(
            os.path.join(root, "**", "xau-depth-account-v230-*.json"),
            recursive=True,
        )
    )
    if not files:
        raise RuntimeError("V233_V230_SHARDS_MISSING")
    rows: list[dict[str, Any]] = []
    years: list[int] = []
    for path in files:
        payload = json.loads(Path(path).read_text())
        if payload.get("research_version") != V230_VERSION:
            raise RuntimeError(f"V233_V230_VERSION_MISMATCH:{path}")
        year = int(payload["year"])
        years.append(year)
        for raw in list(payload.get("orders") or []):
            row = dict(raw)
            if (
                str(row.get("source_layer") or "") not in NESTED_SOURCES
                or str(row.get("target_source") or "") != TERMINAL_TARGET
                or float(row.get("rr") or 0.0) < 1.0
            ):
                continue
            row["engine"] = "REVERSAL"
            row["variant_id"] = "V231_NESTED_TERMINAL"
            row["gross_points"] = float(row.get("gross_pnl_usd") or 0.0)
            row["trade_key"] = "|".join(
                (
                    "REV",
                    str(row.get("candidate_key") or ""),
                    str(row.get("slot") or ""),
                    str(row.get("fill_at") or ""),
                )
            )
            rows.append(row)
    observed = sorted(set(years))
    expected = list(range(2012, 2027))
    if observed != expected:
        raise RuntimeError(f"V233_V230_YEAR_COVERAGE_INVALID:{observed}")
    rows.sort(key=lambda row: (_dt(row["fill_at"]), row["trade_key"]))
    return rows


def _trade_metrics(rows: list[dict[str, Any]], *, friction: float) -> dict[str, Any]:
    pnl = [float(row["gross_points"]) - friction for row in rows]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    years: dict[int, float] = {}
    for row, value in zip(rows, pnl):
        year = int(row["year"])
        years[year] = years.get(year, 0.0) + value
    return {
        "orders": len(rows),
        "net_points_fixed_0_01": sum(pnl),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else None,
        "positive_years": sum(value > 0 for value in years.values()),
        "year_count": len(years),
        "year_net_points": {str(year): value for year, value in sorted(years.items())},
    }


def _select_continuation(rows: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    variants = sorted({str(row["variant_id"]) for row in rows})
    evidence: dict[str, Any] = {}
    eligible: list[tuple[float, float, str]] = []
    for variant in variants:
        train = [
            row for row in rows
            if str(row["variant_id"]) == variant and 2012 <= int(row["year"]) <= 2018
        ]
        metrics = _trade_metrics(train, friction=0.5)
        passed = bool(
            metrics["orders"] >= MIN_TRAIN_TRADES
            and float(metrics.get("profit_factor") or 0.0) >= MIN_TRAIN_PF
            and float(metrics["net_points_fixed_0_01"]) > 0
            and int(metrics["positive_years"]) >= MIN_TRAIN_POSITIVE_YEARS
        )
        evidence[variant] = {
            "train_2012_2018": metrics,
            "selection_passed": passed,
        }
        if passed:
            eligible.append(
                (
                    float(metrics["net_points_fixed_0_01"]),
                    float(metrics.get("profit_factor") or 0.0),
                    variant,
                )
            )
    eligible.sort(reverse=True)
    selected = eligible[0][2] if eligible else None
    return selected, evidence


def _period_metrics(
    rows: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    friction: float = 0.5,
) -> dict[str, Any]:
    subset = [row for row in rows if start <= int(row["year"]) <= end]
    return _trade_metrics(subset, friction=friction)


def _lot_for_trade(
    *,
    balance: float,
    margin_per_001: float,
    used_margin: float,
    margin_fraction: float | None,
) -> float:
    if balance <= 0 or margin_per_001 <= 0:
        return 0.0
    if margin_fraction is None:
        requested = LOT_STEP
    else:
        # Split the allowed account margin budget across the maximum two
        # simultaneous slots so one first-arriving trade cannot monopolize it.
        per_order_budget = balance * float(margin_fraction) / MAX_CONCURRENT
        requested_steps = math.floor(per_order_budget / margin_per_001 + 1e-12)
        requested = requested_steps * LOT_STEP
    requested = min(MAX_LOT, max(0.0, requested))
    if requested < LOT_STEP - 1e-12:
        return 0.0

    # Absolute broker-capital sufficiency remains; there is intentionally no
    # risk-percent filter or risk-based sizing in V233.
    available_cash_margin = max(0.0, balance - used_margin)
    cash_steps = math.floor(available_cash_margin / margin_per_001 + 1e-12)
    cash_lot = cash_steps * LOT_STEP
    lot = min(requested, cash_lot, MAX_LOT)
    return math.floor((lot + 1e-12) / LOT_STEP) * LOT_STEP


def simulate_account(
    rows: list[dict[str, Any]],
    *,
    friction: float,
    margin_fraction: float | None,
    initial_balance: float = INITIAL_BALANCE,
) -> dict[str, Any]:
    balance = float(initial_balance)
    peak = balance
    min_balance = balance
    max_dd = 0.0
    active: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    skipped_cap = 0
    skipped_margin = 0
    target_10k_at: str | None = None

    def realize_until(point: datetime) -> None:
        nonlocal balance, peak, min_balance, max_dd, active, target_10k_at
        closing = sorted(
            [row for row in active if _dt(row["exit_at"]) <= point],
            key=lambda row: _dt(row["exit_at"]),
        )
        closing_ids = {id(row) for row in closing}
        for row in closing:
            balance += float(row["net_pnl_usd"])
            peak = max(peak, balance)
            min_balance = min(min_balance, balance)
            if peak > 0:
                max_dd = max(max_dd, (peak - balance) / peak)
            if target_10k_at is None and balance >= 10000.0:
                target_10k_at = str(row["exit_at"])
        active = [row for row in active if id(row) not in closing_ids]

    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (_dt(row["fill_at"]), row["trade_key"]),
    )
    for row in ordered:
        fill_at = _dt(row["fill_at"])
        realize_until(fill_at)
        if balance <= 0:
            skipped_margin += 1
            continue
        if len(active) >= MAX_CONCURRENT:
            skipped_cap += 1
            continue

        margin_per_001 = float(row.get("margin_usd_1_to_100") or 0.0)
        used_margin = sum(float(item["margin_usd"]) for item in active)
        lot = _lot_for_trade(
            balance=balance,
            margin_per_001=margin_per_001,
            used_margin=used_margin,
            margin_fraction=margin_fraction,
        )
        if lot < LOT_STEP - 1e-12:
            skipped_margin += 1
            continue

        multiplier = lot / LOT_STEP
        margin = margin_per_001 * multiplier
        gross = float(row["gross_points"]) * multiplier
        net = (float(row["gross_points"]) - friction) * multiplier
        enriched = {
            **row,
            "lot": lot,
            "margin_usd": margin,
            "gross_pnl_usd_scaled": gross,
            "net_pnl_usd": net,
        }
        active.append(enriched)
        executed.append(enriched)

    if active:
        final_point = max(_dt(row["exit_at"]) for row in active)
        realize_until(final_point)

    pnl = [float(row["net_pnl_usd"]) for row in executed]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "initial_balance": initial_balance,
        "final_balance": balance,
        "net_profit": balance - initial_balance,
        "return_pct": (balance / initial_balance - 1.0) * 100.0,
        "executed_orders": len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else None,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_realized_drawdown": max_dd,
        "min_realized_balance": min_balance,
        "target_10000_reached": target_10k_at is not None,
        "target_10000_at": target_10k_at,
        "max_lot_used": max((float(row["lot"]) for row in executed), default=0.0),
        "average_lot": (
            sum(float(row["lot"]) for row in executed) / len(executed)
            if executed else 0.0
        ),
        "skipped_position_cap": skipped_cap,
        "skipped_margin": skipped_margin,
        "friction_points_per_order": friction,
        "margin_fraction": margin_fraction,
    }


def _account_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Any] = {}
    for friction in FRICTIONS:
        matrix[f"friction_{friction}"] = {
            "fixed_0_01": simulate_account(
                rows,
                friction=friction,
                margin_fraction=None,
            ),
            **{
                f"margin_{int(fraction * 100)}pct": simulate_account(
                    rows,
                    friction=friction,
                    margin_fraction=fraction,
                )
                for fraction in MARGIN_FRACTIONS
            },
        }
    return matrix


def _rolling_three_year(
    rows: list[dict[str, Any]],
    *,
    friction: float = 0.5,
    margin_fraction: float = 0.50,
) -> list[dict[str, Any]]:
    output = []
    for start in range(2012, 2025):
        end = start + 2
        subset = [row for row in rows if start <= int(row["year"]) <= end]
        output.append(
            {
                "years": [start, end],
                "account": simulate_account(
                    subset,
                    friction=friction,
                    margin_fraction=margin_fraction,
                ),
            }
        )
    return output


def aggregate(continuation_root: str, v230_root: str) -> dict[str, Any]:
    continuation = _load_continuation(continuation_root)
    reversal = _load_v231_reversal(v230_root)
    selected, selection = _select_continuation(continuation)

    selected_cont = (
        [row for row in continuation if str(row["variant_id"]) == selected]
        if selected is not None else []
    )
    portfolio = sorted(
        reversal + selected_cont,
        key=lambda row: (_dt(row["fill_at"]), row["trade_key"]),
    )

    continuation_validation: dict[str, Any] = {}
    if selected is not None:
        continuation_validation = {
            "selected_variant": selected,
            "train_2012_2018": _period_metrics(selected_cont, start=2012, end=2018),
            "test_2019_2024": _period_metrics(selected_cont, start=2019, end=2024),
            "holdout_2025_2026": _period_metrics(selected_cont, start=2025, end=2026),
            "full_2012_2026": _trade_metrics(selected_cont, friction=0.5),
            "by_direction": {
                direction: _trade_metrics(
                    [row for row in selected_cont if row["direction"] == direction],
                    friction=0.5,
                )
                for direction in ("LONG", "SHORT")
            },
        }

    era_accounts = {}
    for name, start, end in (
        ("train_2012_2018", 2012, 2018),
        ("test_2019_2024", 2019, 2024),
        ("holdout_2025_2026", 2025, 2026),
    ):
        subset = [row for row in portfolio if start <= int(row["year"]) <= end]
        era_accounts[name] = _account_matrix(subset)

    full_matrix = _account_matrix(portfolio)
    rolling = _rolling_three_year(portfolio)

    primary = full_matrix["friction_0.5"]["margin_50pct"]
    test_primary = era_accounts["test_2019_2024"]["friction_0.5"]["margin_50pct"]
    holdout_primary = era_accounts["holdout_2025_2026"]["friction_0.5"]["margin_50pct"]
    positive_rolling = sum(
        float(row["account"]["net_profit"]) > 0 for row in rolling
    )

    decision = "HOLD_RESEARCH_ONLY"
    target_10k_historical = any(
        bool(config["target_10000_reached"])
        for friction in full_matrix.values()
        for config in friction.values()
    )
    if (
        selected is not None
        and float(test_primary["net_profit"]) > 0
        and float(holdout_primary["net_profit"]) > 0
        and positive_rolling >= 10
    ):
        decision = "PROSPECTIVE_SHADOW_CANDIDATE"

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "objective": "$200_TO_$10000_WITHOUT_RISK_PERCENT_FILTER",
        "constraints": {
            "initial_balance": INITIAL_BALANCE,
            "leverage": "1:100",
            "max_lot": MAX_LOT,
            "max_concurrent_positions": MAX_CONCURRENT,
            "risk_percent_filter": None,
            "frictions": list(FRICTIONS),
            "margin_fraction_sensitivity": list(MARGIN_FRACTIONS),
            "live_execution": False,
        },
        "selection_contract": {
            "selection_period": [2012, 2018],
            "minimum_train_trades": MIN_TRAIN_TRADES,
            "minimum_train_profit_factor": MIN_TRAIN_PF,
            "minimum_positive_train_years": MIN_TRAIN_POSITIVE_YEARS,
            "selection_score": "MAX_NET_POINTS_AT_FRICTION_0_5_AFTER_GATES",
            "test_period": [2019, 2024],
            "holdout_period": [2025, 2026],
        },
        "continuation_selection": selection,
        "continuation_validation": continuation_validation,
        "reversal_orders": len(reversal),
        "continuation_orders_selected": len(selected_cont),
        "portfolio_candidate_orders": len(portfolio),
        "portfolio_full_2012_2026": full_matrix,
        "portfolio_era_restart": era_accounts,
        "rolling_3y_friction_0_5_margin_50pct": rolling,
        "rolling_3y_positive_windows": positive_rolling,
        "rolling_3y_window_count": len(rolling),
        "historical_target_10000_reached_any_sizing": target_10k_historical,
        "primary_friction_0_5_margin_50pct": primary,
        "decision": decision,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "methodology_note": (
            "Continuation variant selection is frozen to 2012-2018 only. "
            "2019-2024 and 2025-2026 do not participate in variant selection. "
            "V231 reversal remains the frozen H1/M15 nested terminal policy. "
            "M5 is used only after completed M15 setup and completed M5 trigger; "
            "all entries occur at the next M5 open."
        ),
    }


def run() -> int:
    continuation_root = os.environ.get("XAU_V233_CONTINUATION_DIR", "/tmp/v233-cont")
    v230_root = os.environ.get("XAU_V233_V230_DIR", "/tmp/v230-shards")
    output = Path(
        os.environ.get(
            "XAU_V233_FULL_OUTPUT",
            "artifacts/xau-h4-h1-m15-m5-portfolio-v233-full.json",
        )
    )
    result = aggregate(continuation_root, v230_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    primary = result["primary_friction_0_5_margin_50pct"]
    print(
        "XAU_V233_FULL "
        f"selected={result['continuation_validation'].get('selected_variant')} "
        f"orders={result['portfolio_candidate_orders']} "
        f"final_50={primary['final_balance']:.2f} "
        f"dd_50={primary['max_realized_drawdown']:.4f} "
        f"target10k={result['historical_target_10000_reached_any_sizing']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import glob
import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

RESEARCH_VERSION = "XAU_DEPTH_TARGET_WALKFORWARD_V231_1"
ARTIFACT_CONTRACT = "XAU_DEPTH_TARGET_WALKFORWARD_V231_FULL_1"
SOURCE_VERSION = "XAU_DEPTH_ACCOUNT_REPLAY_V230_1"

INITIAL_BALANCE = 200.0
MAX_CONCURRENT_ORDERS = 2
FRICTIONS = (0.0, 0.5, 1.0)
BOOTSTRAP_SAMPLES = 20000
BOOTSTRAP_SEED = 231
MIN_VALIDATION_ORDERS = 30

NESTED_SOURCES = {"H1_NESTED_LOCATOR", "M15_NESTED_LOCATOR"}
TERMINAL_TARGET = "ATLAS_TERMINAL_OPPOSING_ZONE"


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _load_orders(root: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files = sorted(
        glob.glob(
            os.path.join(root, "**", "xau-depth-account-v230-*.json"),
            recursive=True,
        )
    )
    if not files:
        raise RuntimeError("V231_NO_V230_SHARDS")

    orders: list[dict[str, Any]] = []
    years: list[int] = []
    diagnostics: dict[str, int] = {}
    for path in files:
        payload = json.loads(Path(path).read_text())
        if str(payload.get("research_version") or "") != SOURCE_VERSION:
            raise RuntimeError(f"V231_SOURCE_VERSION_MISMATCH:{path}")
        year = int(payload["year"])
        years.append(year)
        orders.extend(dict(row) for row in list(payload.get("orders") or []))
        for key, value in dict(payload.get("diagnostics") or {}).items():
            diagnostics[key] = diagnostics.get(key, 0) + int(value or 0)

    expected = list(range(2012, 2027))
    observed = sorted(set(years))
    if observed != expected:
        raise RuntimeError(f"V231_YEAR_COVERAGE_INVALID:{observed}")

    orders.sort(
        key=lambda row: (
            _dt(row["fill_at"]),
            str(row.get("candidate_key") or ""),
            str(row.get("slot") or ""),
        )
    )
    return orders, {
        "files": len(files),
        "years": observed,
        "diagnostics": diagnostics,
    }


def _frozen_v231(row: dict[str, Any]) -> bool:
    return (
        str(row.get("source_layer") or "") in NESTED_SOURCES
        and str(row.get("target_source") or "") == TERMINAL_TARGET
        and float(row.get("rr") or 0.0) >= 1.0
    )


def _baseline_v229(row: dict[str, Any]) -> bool:
    return float(row.get("rr") or 0.0) >= 1.0


def _subset(
    rows: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    direction: str | None = None,
    source_layer: str | None = None,
    slot: str | None = None,
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        year = int(row["year"])
        if not predicate(row):
            continue
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        if direction is not None and str(row.get("direction") or "") != direction:
            continue
        if source_layer is not None and str(row.get("source_layer") or "") != source_layer:
            continue
        if slot is not None and str(row.get("slot") or "") != slot:
            continue
        result.append(dict(row))
    return result


def simulate_account(
    rows: list[dict[str, Any]],
    *,
    friction_points: float,
    initial_balance: float = INITIAL_BALANCE,
) -> dict[str, Any]:
    balance = float(initial_balance)
    peak_balance = balance
    min_balance = balance
    max_drawdown = 0.0
    active: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    skipped_position_cap = 0
    skipped_margin = 0

    def realize_until(point: datetime) -> None:
        nonlocal balance, peak_balance, min_balance, max_drawdown, active
        closing = sorted(
            [row for row in active if _dt(row["exit_at"]) <= point],
            key=lambda row: _dt(row["exit_at"]),
        )
        closing_ids = {id(row) for row in closing}
        for row in closing:
            pnl = float(row["gross_pnl_usd"]) - float(friction_points)
            balance += pnl
            peak_balance = max(peak_balance, balance)
            min_balance = min(min_balance, balance)
            if peak_balance > 0:
                max_drawdown = max(
                    max_drawdown,
                    (peak_balance - balance) / peak_balance,
                )
        active = [row for row in active if id(row) not in closing_ids]

    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            _dt(row["fill_at"]),
            str(row.get("candidate_key") or ""),
            str(row.get("slot") or ""),
        ),
    )
    for row in ordered:
        fill_at = _dt(row["fill_at"])
        realize_until(fill_at)

        if balance <= 0:
            skipped_margin += 1
            continue
        if len(active) >= MAX_CONCURRENT_ORDERS:
            skipped_position_cap += 1
            continue

        margin = float(row.get("margin_usd_1_to_100") or 0.0)
        used_margin = sum(
            float(item.get("margin_usd_1_to_100") or 0.0)
            for item in active
        )
        # V231 intentionally has no risk-percent cap or risk-based sizing.
        # Broker-style capital sufficiency remains necessary for fixed 0.01 lot.
        if margin <= 0 or used_margin + margin > balance:
            skipped_margin += 1
            continue

        row["net_pnl_usd"] = (
            float(row["gross_pnl_usd"]) - float(friction_points)
        )
        active.append(row)
        executed.append(row)

    realize_until(datetime.max.replace(tzinfo=_dt("2026-01-01T00:00:00+00:00").tzinfo))

    pnl = [float(row["net_pnl_usd"]) for row in executed]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    gross_profit = sum(max(value, 0.0) for value in pnl)
    gross_loss = -sum(min(value, 0.0) for value in pnl)

    return {
        "initial_balance": initial_balance,
        "final_balance": balance,
        "net_profit": balance - initial_balance,
        "return_pct": (
            (balance / initial_balance - 1.0) * 100.0
            if initial_balance else None
        ),
        "executed_orders": len(executed),
        "wins": wins,
        "losses": losses,
        "flats": len(executed) - wins - losses,
        "win_rate": (
            wins / (wins + losses)
            if wins + losses else None
        ),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0 else None
        ),
        "max_realized_drawdown": max_drawdown,
        "min_realized_balance": min_balance,
        "tp_count": sum(
            str(row.get("exit_reason") or "") == "TP"
            for row in executed
        ),
        "sl_count": sum(
            str(row.get("exit_reason") or "").startswith("SL")
            for row in executed
        ),
        "time_exit_count": sum(
            str(row.get("exit_reason") or "").startswith("TIME_EXIT")
            for row in executed
        ),
        "skipped_position_cap": skipped_position_cap,
        "skipped_margin": skipped_margin,
        "friction_points_per_order": friction_points,
    }


def _bootstrap_candidate_net(
    rows: list[dict[str, Any]],
    *,
    friction_points: float,
    seed: int,
) -> dict[str, Any]:
    by_candidate: dict[str, float] = {}
    for row in rows:
        key = str(row.get("candidate_key") or "")
        if not key:
            continue
        by_candidate[key] = by_candidate.get(key, 0.0) + (
            float(row["gross_pnl_usd"]) - float(friction_points)
        )

    values = list(by_candidate.values())
    n = len(values)
    if n == 0:
        return {
            "candidate_count": 0,
            "samples": 0,
            "probability_net_positive": None,
            "net_pnl_ci95": [None, None],
            "median_net_pnl": None,
        }

    rng = random.Random(seed)
    totals: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        totals.append(
            sum(values[rng.randrange(n)] for _ in range(n))
        )
    totals.sort()

    def quantile(q: float) -> float:
        index = max(
            0,
            min(len(totals) - 1, int(round(q * (len(totals) - 1)))),
        )
        return float(totals[index])

    return {
        "candidate_count": n,
        "samples": BOOTSTRAP_SAMPLES,
        "probability_net_positive": (
            sum(total > 0 for total in totals) / len(totals)
        ),
        "net_pnl_ci95": [quantile(0.025), quantile(0.975)],
        "median_net_pnl": quantile(0.5),
        "note": (
            "Candidate-level bootstrap preserves paired NEAR_EDGE/REFERENCE "
            "orders within one candidate. It is descriptive uncertainty, not "
            "proof of independent future performance."
        ),
    }


def _segment(
    rows: list[dict[str, Any]],
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    segment_rows = _subset(
        rows,
        _frozen_v231,
        start_year=start,
        end_year=end,
    )
    return {
        "years": [start, end],
        "frictions": {
            str(friction): simulate_account(
                segment_rows,
                friction_points=friction,
            )
            for friction in FRICTIONS
        },
        "bootstrap_friction_0_5": _bootstrap_candidate_net(
            segment_rows,
            friction_points=0.5,
            seed=BOOTSTRAP_SEED + start,
        ),
    }


def _rolling_three_years(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for start in range(2012, 2025):
        end = start + 2
        segment_rows = _subset(
            rows,
            _frozen_v231,
            start_year=start,
            end_year=end,
        )
        output.append(
            {
                "years": [start, end],
                "friction_0_5": simulate_account(
                    segment_rows,
                    friction_points=0.5,
                ),
            }
        )
    return output


def aggregate(root: str) -> dict[str, Any]:
    rows, source_meta = _load_orders(root)
    frozen = _subset(rows, _frozen_v231)
    baseline = _subset(rows, _baseline_v229)

    chronological = {
        "train_2012_2018": _segment(rows, start=2012, end=2018),
        "test_2019_2024": _segment(rows, start=2019, end=2024),
        "validation_2025_2026": _segment(rows, start=2025, end=2026),
    }
    rolling = _rolling_three_years(rows)

    full = {
        str(friction): simulate_account(
            frozen,
            friction_points=friction,
        )
        for friction in FRICTIONS
    }
    baseline_full = {
        str(friction): simulate_account(
            baseline,
            friction_points=friction,
        )
        for friction in FRICTIONS
    }

    diagnostics = {
        "direction": {
            direction: simulate_account(
                _subset(rows, _frozen_v231, direction=direction),
                friction_points=0.5,
            )
            for direction in ("LONG", "SHORT")
        },
        "source_layer": {
            source: simulate_account(
                _subset(rows, _frozen_v231, source_layer=source),
                friction_points=0.5,
            )
            for source in sorted(NESTED_SOURCES)
        },
        "slot": {
            slot: simulate_account(
                _subset(rows, _frozen_v231, slot=slot),
                friction_points=0.5,
            )
            for slot in ("NEAR_EDGE", "REFERENCE")
        },
    }

    era_05 = [
        chronological[name]["frictions"]["0.5"]
        for name in (
            "train_2012_2018",
            "test_2019_2024",
            "validation_2025_2026",
        )
    ]
    rolling_positive = sum(
        float(item["friction_0_5"]["net_profit"]) > 0
        for item in rolling
    )
    rolling_pf_positive = sum(
        float(item["friction_0_5"].get("profit_factor") or 0.0) > 1.0
        for item in rolling
    )
    validation_orders = int(
        chronological["validation_2025_2026"]["frictions"]["0.5"][
            "executed_orders"
        ]
    )

    evidence_gates = {
        "all_three_eras_positive_at_friction_0_5": all(
            float(item["net_profit"]) > 0 for item in era_05
        ),
        "all_three_eras_pf_gt_1_at_friction_0_5": all(
            float(item.get("profit_factor") or 0.0) > 1.0
            for item in era_05
        ),
        "rolling_3y_positive_windows": rolling_positive,
        "rolling_3y_window_count": len(rolling),
        "rolling_3y_positive_share": (
            rolling_positive / len(rolling) if rolling else None
        ),
        "rolling_3y_pf_gt_1_windows": rolling_pf_positive,
        "validation_orders": validation_orders,
        "minimum_validation_orders_required": MIN_VALIDATION_ORDERS,
        "validation_sample_sufficient": (
            validation_orders >= MIN_VALIDATION_ORDERS
        ),
        "survives_1_point_friction_full_period": (
            float(full["1.0"]["net_profit"]) > 0
            and float(full["1.0"].get("profit_factor") or 0.0) > 1.0
        ),
        "survives_1_point_friction_all_eras": all(
            float(
                chronological[name]["frictions"]["1.0"]["net_profit"]
            ) > 0
            and float(
                chronological[name]["frictions"]["1.0"].get("profit_factor")
                or 0.0
            ) > 1.0
            for name in (
                "train_2012_2018",
                "test_2019_2024",
                "validation_2025_2026",
            )
        ),
    }

    promotion_ready = (
        evidence_gates["all_three_eras_positive_at_friction_0_5"]
        and evidence_gates["all_three_eras_pf_gt_1_at_friction_0_5"]
        and evidence_gates["validation_sample_sufficient"]
        and evidence_gates["survives_1_point_friction_all_eras"]
    )

    decision = (
        "ELIGIBLE_FOR_SEPARATE_PROSPECTIVE_SHADOW_REVIEW"
        if promotion_ready
        else "HOLD_RESEARCH_ONLY"
    )

    return {
        "artifact_contract": ARTIFACT_CONTRACT,
        "research_version": RESEARCH_VERSION,
        "source_research_version": SOURCE_VERSION,
        "frozen_rule": {
            "fresh_h4_parent": "INHERITED_FROM_V230_V226_REPLAY",
            "allowed_source_layers": sorted(NESTED_SOURCES),
            "h4_only_fallback_allowed": False,
            "target_source_required": TERMINAL_TARGET,
            "minimum_rr": 1.0,
            "fixed_lot_per_order": 0.01,
            "max_concurrent_orders": MAX_CONCURRENT_ORDERS,
            "risk_percent_filter": None,
            "initial_balance": INITIAL_BALANCE,
            "leverage": "1:100",
        },
        "source_meta": source_meta,
        "candidate_orders": len(frozen),
        "baseline_v229_candidate_orders": len(baseline),
        "full_2012_2026": full,
        "baseline_v229_full_2012_2026": baseline_full,
        "chronological_walkforward": chronological,
        "rolling_three_year_windows": rolling,
        "diagnostics_friction_0_5": diagnostics,
        "bootstrap_full_friction_0_5": _bootstrap_candidate_net(
            frozen,
            friction_points=0.5,
            seed=BOOTSTRAP_SEED,
        ),
        "evidence_gates": evidence_gates,
        "decision": decision,
        "execution_authority": False,
        "promotion_authority": False,
        "methodology_warning": (
            "The frozen V231 rule was discovered after inspecting the full V230 "
            "sample. Therefore these chronological and rolling results are a "
            "retrospective stability audit, not a pristine unseen out-of-sample "
            "validation. Promotion remains prohibited until sufficient prospective "
            "shadow evidence is accumulated."
        ),
    }


def run() -> int:
    root = os.environ.get("XAU_V231_SHARD_DIR", "/tmp/v230-shards")
    output = os.environ.get(
        "XAU_V231_OUTPUT",
        "artifacts/xau-depth-target-walkforward-v231-full.json",
    )
    result = aggregate(root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True))
    full = result["full_2012_2026"]["0.5"]
    gates = result["evidence_gates"]
    print(
        "XAU_V231_WALKFORWARD "
        f"orders={result['candidate_orders']} "
        f"final_0_5={full['final_balance']:.2f} "
        f"pf_0_5={full['profit_factor']:.4f} "
        f"rolling_positive={gates['rolling_3y_positive_windows']}/"
        f"{gates['rolling_3y_window_count']} "
        f"validation_n={gates['validation_orders']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

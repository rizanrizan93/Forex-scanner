"""Read-only, causal replay of pre-touch XAU entry and structural TP pairs.

The V242 plan is frozen before the first H4 touch. Only slots 1/2 and their
precomputed structural targets are eligible. M5-activated slots 3/4 have no
known entry or TP at plan time and must never enter this comparison.
"""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Sequence

import pandas as pd

from .research_xau_v229_historical_v242 import (
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    MIN_TERMINAL_RR,
    STRESS_SLIPPAGE_MULTIPLIER,
    STRESS_SPREAD_MULTIPLIER,
    _dt,
    _simulate_limit_trade,
    price_arrays,
)

RESEARCH_VERSION = "XAU_JOINT_ENTRY_TP_V280_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False
MIN_TRAIN_PLANS = 30
MIN_TEST_PLANS = 30


def _candidates(plan: dict[str, Any]) -> dict[str, tuple[float, float]]:
    direction = str(plan.get("direction") or "").upper()
    stop = float(plan["stop"])
    slots = {
        int(child["slot"]): child
        for child in plan.get("children", [])
        if int(child["slot"]) in (1, 2)
    }
    if direction not in ("LONG", "SHORT") or 1 not in slots:
        return {}
    candidates: dict[str, tuple[float, float]] = {}
    for entry_slot in (1, 2):
        if entry_slot not in slots:
            continue
        entry = float(slots[entry_slot]["reference_price"])
        risk = entry - stop if direction == "LONG" else stop - entry
        if not isfinite(risk) or risk <= 0:
            continue
        for target_slot in (1, 2):
            target = slots.get(target_slot, {}).get("planned_target")
            if target is None:
                continue
            target = float(target)
            reward = target - entry if direction == "LONG" else entry - target
            if not isfinite(reward) or reward / risk < MIN_TERMINAL_RR:
                continue
            candidates[f"E{entry_slot}_T{target_slot}"] = (entry, target)
    return candidates


def replay_plan(plan: dict[str, Any], m1: pd.DataFrame) -> dict[str, Any]:
    """Score a frozen plan at base and stress costs, with misses as zero R.

    The V242 simulator is conservative on ambiguous stop/target bars. Plans
    lacking a full 30-day price horizon are marked censored, never scored.
    """
    at = _dt(plan.get("plan_at"))
    expires = _dt(plan.get("signal_expires_at"))
    if at is None or expires is None or expires <= at:
        raise ValueError("invalid plan timestamps")
    if m1.empty or "timestamp" not in m1:
        raise ValueError("missing M1 bars")
    px = price_arrays(m1)
    if (px.timestamps[-1] < pd.Timestamp(expires) + pd.Timedelta(days=30)
        or not any(pd.Timestamp(at) < ts <= pd.Timestamp(expires) for ts in px.timestamps)):
        return {"plan_id": plan.get("plan_id"), "year": at.year, "censored": True}

    result: dict[str, Any] = {
        "plan_id": plan.get("plan_id"),
        "year": at.year,
        "mature_at": (expires + pd.Timedelta(days=30)).isoformat(),
        "censored": False,
        "pairs": {},
    }
    for key, (entry, target) in _candidates(plan).items():
        costs: dict[str, Any] = {}
        for mode, spread, slip in (
            ("base", BASE_SPREAD_PIPS, BASE_SLIPPAGE_PIPS),
            ("stress", BASE_SPREAD_PIPS * STRESS_SPREAD_MULTIPLIER,
             BASE_SLIPPAGE_PIPS * STRESS_SLIPPAGE_MULTIPLIER),
        ):
            trade = _simulate_limit_trade(
                px=px, direction=str(plan["direction"]).upper(),
                order_at=at, expires_at=expires, entry=entry,
                stop=float(plan["stop"]), target=target,
                spread_pips=spread, slippage_pips=slip,
            )
            state = trade["state"]
            # A missing entry is a zero-return opportunity. Invalid geometry,
            # incomplete history and simulated open trades cannot be scored.
            if state not in ("MISSED", "WIN", "LOSS", "BREAKEVEN"):
                costs = {}
                break
            if state != "MISSED" and "net_r" not in trade:
                costs = {}
                break
            costs[mode] = {
                "state": state,
                "net_r_per_opportunity": float(trade.get("net_r", 0.0)),
                "reason": trade.get("reason"),
                "ambiguous_bar": bool(trade.get("ambiguous_bar", False)),
            }
        if len(costs) == 2:
            result["pairs"][key] = costs
    return result


def _metrics(rows: Sequence[dict[str, Any]], key: str, mode: str) -> dict[str, Any]:
    selected = [row["pairs"][key][mode] for row in rows if key in row.get("pairs", {})]
    n = len(selected)
    filled = [row for row in selected if row["state"] != "MISSED"]
    return {
        "opportunities": n,
        "fill_rate": len(filled) / n if n else None,
        "expectancy_r_per_opportunity": (
            sum(row["net_r_per_opportunity"] for row in selected) / n if n else None
        ),
        "ambiguous_bars": sum(bool(row["ambiguous_bar"]) for row in selected),
    }


def walk_forward(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Choose a pair from preceding years only; compare it to frozen E1_T1."""
    usable = [row for row in rows if not row.get("censored")]
    years: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in usable:
        years[int(row["year"])].append(row)
    folds = []
    for year in sorted(years):
        cutoff = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
        train = [
            row for prior in sorted(years) if prior < year for row in years[prior]
            if row.get("mature_at") and pd.Timestamp(row["mature_at"]) < cutoff
        ]
        test = years[year]
        keys = sorted(set.intersection(*(set(row.get("pairs", {})) for row in train))) if train else []
        if len(train) < MIN_TRAIN_PLANS or len(test) < MIN_TEST_PLANS or "E1_T1" not in keys:
            folds.append({"test_year": year, "eligible": False, "reason": "INSUFFICIENT_PAIRED_HISTORY"})
            continue
        eligible = [key for key in keys if _metrics(train, key, "stress")["expectancy_r_per_opportunity"] > 0]
        if not eligible:
            folds.append({"test_year": year, "eligible": False, "reason": "NO_POSITIVE_STRESS_PAIR"})
            continue
        chosen = max(eligible, key=lambda key: (
            _metrics(train, key, "base")["expectancy_r_per_opportunity"], key
        ))
        # Decide using training alone. Missing either candidate in the test
        # sample invalidates the whole paired fold, never just a losing row.
        if any("E1_T1" not in row.get("pairs", {}) or chosen not in row["pairs"] for row in test):
            folds.append({"test_year": year, "eligible": False, "reason": "INCOMPLETE_PAIRED_TEST_GRID"})
            continue
        folds.append({
            "test_year": year,
            "eligible": True,
            "selected_pair": chosen,
            "train_plans": len(train),
            "test_plans": len(test),
            "baseline": {mode: _metrics(test, "E1_T1", mode) for mode in ("base", "stress")},
            "selected": {mode: _metrics(test, chosen, mode) for mode in ("base", "stress")},
        })
    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "plans": len(rows),
        "censored_plans": len(rows) - len(usable),
        "folds": folds,
    }

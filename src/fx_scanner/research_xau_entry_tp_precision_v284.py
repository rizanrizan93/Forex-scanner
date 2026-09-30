"""Shadow replay of quote-side XAU limits, structural TP and $5 excursion.

All candidate levels come from the frozen V242 plan. M1 OHLC is a mid-price
proxy: same-bar paths and actual broker fills cannot be recovered from candles.
Stops win ties, and the fill candle cannot win a target. No execution authority.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from math import sqrt
from statistics import median
from typing import Any, Sequence

import pandas as pd

from .research_xau_joint_entry_tp_v280 import _candidates
from .research_xau_v229_historical_v242 import (
    BASE_SLIPPAGE_PIPS, BASE_SPREAD_PIPS, COMMISSION_PIPS_ROUND_TRIP,
    MAX_POSITION_HOLD, PIP_SIZE, STRESS_SLIPPAGE_MULTIPLIER,
    STRESS_SPREAD_MULTIPLIER, _dt, price_arrays,
    effective_trades, PriceArrays,
)

RESEARCH_VERSION = "XAU_ENTRY_TP_PRECISION_V284_1"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
MAX_ENTRY_ERROR_USD = 5.0
MIN_TRAIN_PLANS = 30
MIN_TEST_PLANS = 30


def quote_side_replay(
    *, px: Any, direction: str, order_at: Any, expires_at: Any,
    entry: float, stop: float, target: float,
    spread_pips: float, slippage_pips: float,
) -> dict[str, Any]:
    """Conservative OHLC proxy: ask fills buys; bid fills sells/exits buys."""
    half = spread_pips * PIP_SIZE / 2.0
    slip = slippage_pips * PIP_SIZE
    start = bisect_right(px.timestamps, pd.Timestamp(order_at))
    end = bisect_right(px.timestamps, pd.Timestamp(expires_at))
    if direction not in ("LONG", "SHORT") or end <= start:
        return {"state": "UNRESOLVED", "reason": "NO_PENDING_WINDOW"}
    fill_at = None
    for i in range(start, end):
        if ((direction == "LONG" and px.lows[i] + half <= entry)
            or (direction == "SHORT" and px.highs[i] - half >= entry)):
            fill_at = i
            break
    if fill_at is None:
        return {"state": "MISSED", "reason": "QUOTE_SIDE_LIMIT_NOT_TOUCHED", "net_r": 0.0}

    fill = entry + slip if direction == "LONG" else entry - slip
    risk = fill - stop if direction == "LONG" else stop - fill
    reward = target - fill if direction == "LONG" else fill - target
    if risk <= 0 or reward <= 0:
        return {"state": "UNRESOLVED", "reason": "INVALID_GEOMETRY_AFTER_COST"}
    horizon = pd.Timestamp(px.timestamps[fill_at]) + pd.Timedelta(MAX_POSITION_HOLD)
    last = min(len(px.timestamps), bisect_right(px.timestamps, horizon))
    adverse = 0.0
    for i in range(fill_at, last):
        if direction == "LONG":
            adverse = max(adverse, fill - (float(px.lows[i]) - half))
            stop_hit = float(px.lows[i]) - half <= stop
            tp_hit = float(px.highs[i]) - half >= target
        else:
            adverse = max(adverse, float(px.highs[i]) + half - fill)
            stop_hit = float(px.highs[i]) + half >= stop
            tp_hit = float(px.lows[i]) + half <= target
        # Without ticks a target on the fill bar could precede the fill.
        if i == fill_at:
            tp_hit = False
        if stop_hit or tp_hit:
            reason = "STOP_FIRST_AMBIGUOUS" if stop_hit and tp_hit else "STOP_HIT" if stop_hit else "TARGET_HIT"
            exit_price = stop if stop_hit else target
            gross = (exit_price - fill) if direction == "LONG" else (fill - exit_price)
            net_r = (gross - COMMISSION_PIPS_ROUND_TRIP * PIP_SIZE) / risk
            return {
                "state": "STOP" if stop_hit else "TP", "reason": reason,
                "net_r": net_r, "fill_at": px.timestamps[fill_at].isoformat(),
                "exit_at": px.timestamps[i].isoformat(),
                "max_adverse_usd": max(0.0, adverse),
                "precision_5_and_tp": bool(tp_hit and adverse <= MAX_ENTRY_ERROR_USD),
            }
    if last <= fill_at:
        return {"state": "UNRESOLVED", "reason": "NO_POST_FILL_HISTORY"}
    close = float(px.closes[last - 1]) - half if direction == "LONG" else float(px.closes[last - 1]) + half
    gross = close - fill if direction == "LONG" else fill - close
    return {
        "state": "TIME_EXIT", "reason": "MAX_30D_RESEARCH_HOLD",
        "net_r": (gross - COMMISSION_PIPS_ROUND_TRIP * PIP_SIZE) / risk,
        "fill_at": px.timestamps[fill_at].isoformat(),
        "exit_at": px.timestamps[last - 1].isoformat(),
        "max_adverse_usd": max(0.0, adverse),
        "precision_5_and_tp": False,
    }


def replay_plan(plan: dict[str, Any], m1: pd.DataFrame | PriceArrays) -> dict[str, Any]:
    at = _dt(plan.get("plan_at"))
    expiry = _dt(plan.get("signal_expires_at"))
    if at is None or expiry is None or expiry <= at:
        raise ValueError("invalid plan timestamps")
    if isinstance(m1, PriceArrays):
        px = m1
    else:
        if m1.empty:
            raise ValueError("missing M1 price history")
        px = price_arrays(m1)
    if not px.timestamps:
        raise ValueError("missing M1 price history")
    mature = pd.Timestamp(expiry) + pd.Timedelta(MAX_POSITION_HOLD)
    if px.timestamps[-1] < mature or bisect_right(px.timestamps, pd.Timestamp(at)) == bisect_right(px.timestamps, pd.Timestamp(expiry)):
        return {"plan_id": plan.get("plan_id"), "year": at.year, "censored": True}
    pairs: dict[str, Any] = {}
    candidates = _candidates(plan)
    for key in ("E1_T1", "E1_T2", "E2_T1", "E2_T2"):
        if key not in candidates:
            no_order = {"state": "MISSED", "reason": "NO_VALID_STRUCTURAL_PAIR",
                        "net_r": 0.0, "precision_5_and_tp": False}
            pairs[key] = {"base": dict(no_order), "stress": dict(no_order)}
            continue
        entry, target = candidates[key]
        scenarios = {}
        for mode, spread, slip in (
            ("base", BASE_SPREAD_PIPS, BASE_SLIPPAGE_PIPS),
            ("stress", BASE_SPREAD_PIPS * STRESS_SPREAD_MULTIPLIER,
             BASE_SLIPPAGE_PIPS * STRESS_SLIPPAGE_MULTIPLIER),
        ):
            scenarios[mode] = quote_side_replay(
                px=px, direction=str(plan["direction"]).upper(),
                order_at=at, expires_at=expiry, entry=entry,
                stop=float(plan["stop"]), target=target,
                spread_pips=spread, slippage_pips=slip,
            )
        if all(row["state"] != "UNRESOLVED" for row in scenarios.values()):
            pairs[key] = scenarios
    return {
        "plan_id": plan.get("plan_id"), "year": at.year,
        "mature_at": mature.isoformat(), "censored": False, "pairs": pairs,
    }


def _wilson_lower(successes: int, total: int) -> float | None:
    if total <= 0:
        return None
    z = 1.95996398454
    p = successes / total
    return ((p + z * z / (2 * total)) - z * sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / (1 + z * z / total)


def metrics(rows: Sequence[dict[str, Any]], key: str, mode: str) -> dict[str, Any]:
    sample = [row["pairs"][key][mode] for row in rows]
    n = len(sample)
    filled = [row for row in sample if row["state"] != "MISSED"]
    hits = [row for row in filled if row["state"] == "TP"]
    precise = [row for row in hits if row["precision_5_and_tp"]]
    return {
        "opportunities": n,
        "fill_rate": len(filled) / n if n else None,
        "tp_given_fill": len(hits) / len(filled) if filled else None,
        "tp_per_opportunity": len(hits) / n if n else None,
        "precision_5_and_tp_given_fill": len(precise) / len(filled) if filled else None,
        "joint_success_per_opportunity": len(precise) / n if n else None,
        "joint_wilson_95_lower": _wilson_lower(len(precise), n),
        "expectancy_r_per_opportunity": sum(row["net_r"] for row in sample) / n if n else None,
        "filled": len(filled), "tp": len(hits), "precise_tp": len(precise),
    }


def walk_forward(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    years: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("censored"):
            years[int(row["year"])].append(row)
    folds = []
    for year, test in sorted(years.items()):
        cutoff = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
        train = [row for yr, group in years.items() if yr < year for row in group
                 if row.get("mature_at") and pd.Timestamp(row["mature_at"]) < cutoff]
        keys = set.intersection(*(set(row.get("pairs", {})) for row in train)) if train else set()
        if len(train) < MIN_TRAIN_PLANS or len(test) < MIN_TEST_PLANS or "E1_T1" not in keys:
            folds.append({"test_year": year, "eligible": False, "reason": "INSUFFICIENT_PAIRED_HISTORY"})
            continue
        baseline = metrics(train, "E1_T1", "base")
        admissible = []
        for key in sorted(keys):
            base = metrics(train, key, "base")
            stress = metrics(train, key, "stress")
            if (base["fill_rate"] >= baseline["fill_rate"] - 0.05
                and base["tp_per_opportunity"] >= baseline["tp_per_opportunity"]
                and stress["expectancy_r_per_opportunity"] > 0):
                admissible.append((base["joint_wilson_95_lower"], base["expectancy_r_per_opportunity"], key))
        if not admissible:
            folds.append({"test_year": year, "eligible": False, "reason": "NO_TRAINING_PAIR_MEETS_FILL_TP_STRESS"})
            continue
        chosen = max(admissible)[2]
        if any("E1_T1" not in row["pairs"] or chosen not in row["pairs"] for row in test):
            folds.append({"test_year": year, "eligible": False, "reason": "INCOMPLETE_PAIRED_TEST_GRID"})
            continue
        folds.append({
            "test_year": year, "eligible": True, "selected_pair": chosen,
            "train_plans": len(train), "test_plans": len(test),
            "baseline": {mode: metrics(test, "E1_T1", mode) for mode in ("base", "stress")},
            "selected": {mode: metrics(test, chosen, mode) for mode in ("base", "stress")},
        })
    return {
        "research_version": RESEARCH_VERSION, "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "max_entry_error_usd": MAX_ENTRY_ERROR_USD,
        "fill_proxy": "M1_MID_OHLC_FIXED_SPREAD_QUOTE_SIDE_NOT_BROKER_FILL",
        "same_bar_policy": "STOP_FIRST_TARGET_ON_FILL_BAR_IGNORED",
        "plans": len(rows), "censored_plans": sum(bool(row.get("censored")) for row in rows),
        "folds": folds,
    }


def baseline_from_v242_shards(shards: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Audit the existing V242 paired opportunity ledger without M1 reruns.

    V242 uses mid-OHLC touch fills; this establishes a historical baseline,
    not broker-confirmed fill probability or independent OOS performance.
    """
    plans = [plan for shard in shards for plan in shard.get("plans", [])]
    trades = [trade for shard in shards for trade in shard.get("trades", [])]
    effective, _ = effective_trades(plans, trades)
    eras = {
        "2012_2018": range(2012, 2019),
        "2019_2024": range(2019, 2025),
        "2025_2026": range(2025, 2027),
        "ALL": range(2012, 2027),
    }
    output: dict[str, Any] = {}
    for era, years in eras.items():
        output[era] = {}
        for slot in (1, 2, 3, 4):
            rows = [row for row in effective if row.get("cost_mode") == "BASE"
                    and row.get("slot") == slot and row.get("year") in years]
            filled = [row for row in rows if row.get("state") in ("WIN", "LOSS", "BREAKEVEN")]
            tp = [row for row in filled if row.get("reason") == "TARGET_HIT"]
            excursions = [float(row["mae_r"]) * float(row["risk_pips"]) * PIP_SIZE for row in tp]
            precise = sum(value <= MAX_ENTRY_ERROR_USD for value in excursions)
            n = len(rows)
            output[era][f"L{slot}"] = {
                "opportunities": n, "filled": len(filled), "tp": len(tp),
                "tp_with_adverse_at_most_5_usd": precise,
                "fill_rate": len(filled) / n if n else None,
                "tp_given_fill": len(tp) / len(filled) if filled else None,
                "joint_success_per_opportunity": precise / n if n else None,
                "tp_mae_median_usd": median(excursions) if excursions else None,
            }
    return {
        "research_version": RESEARCH_VERSION,
        "source_version": "XAU_V229_HISTORICAL_EXECUTION_V242_1",
        "year_count": len({shard.get("year") for shard in shards}),
        "price_end_by_year": {str(shard.get("year")): shard.get("price_end") for shard in shards},
        "parent_plans": len(plans), "raw_trade_records": len(trades),
        "max_entry_error_usd": MAX_ENTRY_ERROR_USD,
        "measurement": "MAX_M1_OHLC_ADVERSE_EXCURSION_FROM_FILL_THROUGH_TP",
        "limitations": ["V242_MID_OHLC_TOUCH_FILL_NOT_BROKER_CONFIRMED",
                        "RETROSPECTIVE_CURRENT_PARAMETER_REPLAY_NOT_INDEPENDENT_OOS",
                        "M5_CONFIRMED_SLOTS_HAVE_DIFFERENT_ACTIVATION_AND_FILL_OPPORTUNITY"],
        "execution_influence": False, "execution_authority": False,
        "eras": output,
    }

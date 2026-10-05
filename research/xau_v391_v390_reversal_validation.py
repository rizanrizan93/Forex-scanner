from __future__ import annotations

"""Causal zone/direction validation for the V390 simple local reversal engine.

This is research-only. It does not change V390 production behavior and does not
create DEMO/LIVE execution authority.

Primary question:
    At T-15 minutes before a known causal H1/H4 first-touch episode, does V390
    already expose a tradeable local zone on the relevant side, and if that
    local zone is touched, does price reverse >=0.50 ATR before structural
    invalidation?

The neutral 0.50 ATR reaction threshold follows the existing V345/V376 replay
convention. It is a zone-reaction label, not a trade PnL or win-rate claim.
"""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from fx_scanner.models import ensure_utc
from fx_scanner.research_xau_sd_liquidity_v345 import (
    bars_from_frame,
    build_htf_zones,
    causal_superseded_at,
    evaluate_first_touch,
    load_price_frame,
    resample_ohlc,
)
from fx_scanner.xau_sd_liquidity_engine_v342 import evaluate_sd_liquidity
from fx_scanner.xau_simple_reversal_engine_v390 import evaluate_simple_reversal

SCHEMA = "XAU_V391_V390_LOCAL_REVERSAL_VALIDATION_V1"
PRIMARY_OFFSET_MINUTES = -15
SECONDARY_OFFSET_MINUTES = 0
REACTION_ATR = 0.50
WINDOWS = {"H4": 400, "H1": 560, "M15": 256, "M5": 384}
RULES = {"H4": "4h", "H1": "1h", "M15": "15min", "M5": "5min"}
TF_MINUTES = {"H4": 240, "H1": 60, "M15": 15, "M5": 5}

# Frozen before outcomes are inspected. These gates validate mapping only.
PASS_CRITERIA = {
    "min_episode_count_each_year": 100,
    "min_primary_candidate_coverage": 0.60,
    "min_scored_local_touches_each_year": 40,
    "min_reversal_success_rate_each_year": 0.55,
    "min_combined_reversal_success_rate": 0.60,
    "min_local_before_deep_rate_combined": 0.50,
    "ready_precision_floor_if_n_ge_10": 0.60,
}


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _completed_window(frame: pd.DataFrame, timeframe: str, as_of: datetime) -> pd.DataFrame:
    delta = pd.Timedelta(minutes=TF_MINUTES[timeframe])
    known = frame[(frame["timestamp"] + delta) <= pd.Timestamp(ensure_utc(as_of))]
    return known.tail(WINDOWS[timeframe]).reset_index(drop=True)


def _price_before(price: pd.DataFrame, as_of: datetime) -> float | None:
    rows = price[price["timestamp"] < pd.Timestamp(ensure_utc(as_of))]
    if rows.empty:
        return None
    return float(rows.iloc[-1]["close"])


def _distance_to_band(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    if price < low:
        return low - price
    return price - high


def _zone_overlap(candidate: dict[str, Any], touched_zone: Any) -> float:
    if not candidate:
        return 0.0
    low = _f(candidate.get("low"))
    high = _f(candidate.get("high"))
    if low is None or high is None or high <= low:
        return 0.0
    lo = max(low, float(touched_zone.low))
    hi = min(high, float(touched_zone.high))
    overlap = max(0.0, hi - lo)
    denom = max(1e-9, min(high - low, float(touched_zone.high) - float(touched_zone.low)))
    return overlap / denom


def _invalidation(candidate: dict[str, Any], atr: float) -> float | None:
    if not candidate:
        return None
    low = _f(candidate.get("low"))
    high = _f(candidate.get("high"))
    if low is None or high is None or high <= low:
        return None
    buffer = max(0.12 * atr, 0.15 * (high - low))
    if str(candidate.get("direction") or "").upper() == "LONG":
        return low - buffer
    return high + buffer


def _first_band_touch(rows: pd.DataFrame, low: float, high: float) -> int | None:
    for idx, row in rows.iterrows():
        if float(row["high"]) >= low and float(row["low"]) <= high:
            return int(idx)
    return None


def _score_local_candidate(
    price: pd.DataFrame,
    *,
    as_of: datetime,
    outcome_at: datetime,
    candidate: dict[str, Any],
    atr: float,
    deep_fallback: dict[str, Any],
) -> dict[str, Any]:
    if not candidate or atr <= 0:
        return {"state": "NO_CANDIDATE"}

    low = _f(candidate.get("low"))
    high = _f(candidate.get("high"))
    direction = str(candidate.get("direction") or "").upper()
    invalidation = _invalidation(candidate, atr)
    if low is None or high is None or invalidation is None or direction not in {"LONG", "SHORT"}:
        return {"state": "INVALID_GEOMETRY"}

    future = price[
        (price["timestamp"] >= pd.Timestamp(ensure_utc(as_of)))
        & (price["timestamp"] <= pd.Timestamp(ensure_utc(outcome_at)))
    ].reset_index(drop=True)
    if future.empty:
        return {"state": "NO_FUTURE_ROWS"}

    touch_i = _first_band_touch(future, low, high)
    if touch_i is None:
        return {
            "state": "NOT_TOUCHED",
            "touched": False,
            "invalidation": invalidation,
        }

    touched_at = pd.Timestamp(future.iloc[touch_i]["timestamp"]).isoformat()
    success_level = high + REACTION_ATR * atr if direction == "LONG" else low - REACTION_ATR * atr
    success_i: int | None = None
    invalid_i: int | None = None
    ambiguous = False

    for idx in range(touch_i, len(future)):
        row = future.iloc[idx]
        if direction == "LONG":
            success = float(row["high"]) >= success_level
            invalid = float(row["low"]) <= invalidation
        else:
            success = float(row["low"]) <= success_level
            invalid = float(row["high"]) >= invalidation
        if success and invalid:
            ambiguous = True
            success_i = idx
            invalid_i = idx
            break
        if success:
            success_i = idx
            break
        if invalid:
            invalid_i = idx
            break

    if ambiguous:
        outcome = "AMBIGUOUS_SAME_M1_BAR"
    elif success_i is not None:
        outcome = "REVERSAL_050_ATR"
    elif invalid_i is not None:
        outcome = "INVALIDATED_FIRST"
    else:
        outcome = "TIMEOUT"

    deep_touch_i: int | None = None
    deep_low = _f(deep_fallback.get("low"))
    deep_high = _f(deep_fallback.get("high"))
    if deep_low is not None and deep_high is not None and deep_high > deep_low:
        deep_touch_i = _first_band_touch(future, deep_low, deep_high)

    return {
        "state": outcome,
        "touched": True,
        "touch_at": touched_at,
        "success": outcome == "REVERSAL_050_ATR",
        "ambiguous": ambiguous,
        "success_level": success_level,
        "invalidation": invalidation,
        "local_touch_before_deep": deep_touch_i is None or touch_i < deep_touch_i,
        "deep_touched": deep_touch_i is not None,
    }


def _snapshot(
    *,
    frames: dict[str, pd.DataFrame],
    price: pd.DataFrame,
    as_of: datetime,
    outcome_at: datetime,
    touched_zone: Any,
) -> dict[str, Any]:
    h4 = _completed_window(frames["H4"], "H4", as_of)
    h1 = _completed_window(frames["H1"], "H1", as_of)
    m15 = _completed_window(frames["M15"], "M15", as_of)
    m5 = _completed_window(frames["M5"], "M5", as_of)
    if len(h4) < 24 or len(h1) < 24 or len(m15) < 20 or len(m5) < 20:
        return {"as_of": as_of.isoformat(), "state": "INSUFFICIENT_WINDOW"}

    px = _price_before(price, as_of)
    if px is None:
        return {"as_of": as_of.isoformat(), "state": "NO_PRICE"}

    sd = evaluate_sd_liquidity(
        bars_h1=bars_from_frame(h1, "H1"),
        bars_h4=bars_from_frame(h4, "H4"),
        bars_m15=bars_from_frame(m15, "M15"),
        bars_m5=bars_from_frame(m5, "M5"),
        as_of=as_of,
        price_now=px,
    )
    plan = evaluate_simple_reversal(sd)
    direction = str(touched_zone.direction).upper()
    candidate = _d(plan.get("long_zone" if direction == "LONG" else "short_zone"))
    readiness = str(plan.get("long_readiness" if direction == "LONG" else "short_readiness") or "NONE")
    deep = _d(plan.get("deep_htf_fallback"))
    atr = float(plan.get("atr_reference") or 0.0)

    local_distance = None
    if candidate:
        local_distance = _distance_to_band(px, float(candidate["low"]), float(candidate["high"]))
    deep_distance = None
    deep_low = _f(deep.get("low"))
    deep_high = _f(deep.get("high"))
    if deep_low is not None and deep_high is not None and deep_high > deep_low:
        deep_distance = _distance_to_band(px, deep_low, deep_high)

    score = _score_local_candidate(
        price,
        as_of=as_of,
        outcome_at=outcome_at,
        candidate=candidate,
        atr=atr,
        deep_fallback=deep,
    )

    return {
        "as_of": as_of.isoformat(),
        "state": "OK",
        "price_now": px,
        "plan_state": plan.get("state"),
        "plan_direction": plan.get("direction"),
        "atr_reference": atr,
        "candidate_available": bool(candidate),
        "candidate": candidate,
        "candidate_readiness": readiness,
        "candidate_overlap_touched_zone": _zone_overlap(candidate, touched_zone),
        "candidate_exact_zone_id": bool(candidate.get("zone_id")) and str(candidate.get("zone_id")) == str(touched_zone.zone_id),
        "local_distance_points": local_distance,
        "deep_distance_points": deep_distance,
        "local_closer_than_deep": (
            local_distance is not None
            and deep_distance is not None
            and local_distance < deep_distance - 1e-9
        ),
        "deep_fallback": deep,
        "score": score,
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    return None if not rows else sum(bool(row.get(field)) for row in rows) / len(rows)


def run(year: int, csv_path: Path, output: Path) -> dict[str, Any]:
    price = load_price_frame(csv_path)
    frames = {tf: resample_ohlc(price, rule) for tf, rule in RULES.items()}
    zones = build_htf_zones(price)
    superseded = causal_superseded_at(zones)
    episodes: list[dict[str, Any]] = []

    for zone in zones:
        valid_until = superseded.get(zone.zone_id)
        episode = evaluate_first_touch(price, zone=zone, valid_until=valid_until)
        if not episode:
            continue
        touch_at = ensure_utc(datetime.fromisoformat(str(episode["touch_at"]).replace("Z", "+00:00")))
        if touch_at.year != year:
            continue
        outcome_at = ensure_utc(datetime.fromisoformat(str(episode["outcome_at"]).replace("Z", "+00:00")))

        primary = _snapshot(
            frames=frames,
            price=price,
            as_of=touch_at + timedelta(minutes=PRIMARY_OFFSET_MINUTES),
            outcome_at=outcome_at,
            touched_zone=zone,
        )
        touch_snapshot = _snapshot(
            frames=frames,
            price=price,
            as_of=touch_at + timedelta(minutes=SECONDARY_OFFSET_MINUTES),
            outcome_at=outcome_at,
            touched_zone=zone,
        )

        pscore = _d(primary.get("score"))
        episodes.append({
            "zone_id": zone.zone_id,
            "timeframe": zone.timeframe,
            "direction": zone.direction,
            "zone_low": float(zone.low),
            "zone_high": float(zone.high),
            "touch_at": episode["touch_at"],
            "outcome_at": episode["outcome_at"],
            "legacy_reaction_hit_050_atr": bool(episode.get("reaction_hit")),
            "legacy_break_hit": bool(episode.get("break_hit")),
            "primary": primary,
            "touch_snapshot": touch_snapshot,
            "primary_candidate_available": bool(primary.get("candidate_available")),
            "primary_candidate_touched": bool(pscore.get("touched")),
            "primary_candidate_success": bool(pscore.get("success")),
            "primary_candidate_ambiguous": bool(pscore.get("ambiguous")),
            "primary_local_closer_than_deep": bool(primary.get("local_closer_than_deep")),
            "primary_local_touch_before_deep": bool(pscore.get("local_touch_before_deep")) if pscore.get("touched") else False,
            "primary_ready_early": str(primary.get("candidate_readiness")) == "READY_EARLY",
            "touch_candidate_available": bool(touch_snapshot.get("candidate_available")),
        })

    valid_primary = [e for e in episodes if _d(e.get("primary")).get("state") == "OK"]
    available = [e for e in valid_primary if e["primary_candidate_available"]]
    touched = [e for e in available if e["primary_candidate_touched"]]
    scored = [e for e in touched if not e["primary_candidate_ambiguous"] and _d(_d(e.get("primary")).get("score")).get("state") in {"REVERSAL_050_ATR", "INVALIDATED_FIRST", "TIMEOUT"}]
    ready = [e for e in available if e["primary_ready_early"]]
    ready_touched = [e for e in ready if e["primary_candidate_touched"] and not e["primary_candidate_ambiguous"]]
    ready_success = [e for e in ready_touched if e["primary_candidate_success"]]
    closer = [e for e in available if e["primary_local_closer_than_deep"]]
    closer_touched = [e for e in closer if e["primary_candidate_touched"]]
    local_before_deep = [e for e in closer_touched if e["primary_local_touch_before_deep"]]

    summary = {
        "episodes": len(episodes),
        "valid_primary_snapshots": len(valid_primary),
        "primary_candidate_coverage": _rate(valid_primary, "primary_candidate_available"),
        "primary_candidate_available_count": len(available),
        "primary_candidate_touch_rate": _rate(available, "primary_candidate_touched"),
        "primary_candidate_touched_count": len(touched),
        "scored_local_touch_count": len(scored),
        "reversal_050_before_invalidation_rate": _rate(scored, "primary_candidate_success"),
        "legacy_htf_reaction_050_rate": _rate(episodes, "legacy_reaction_hit_050_atr"),
        "local_closer_than_deep_rate": _rate(available, "primary_local_closer_than_deep"),
        "local_closer_than_deep_count": len(closer),
        "local_touch_before_deep_rate": None if not closer_touched else len(local_before_deep) / len(closer_touched),
        "local_touch_before_deep_denominator": len(closer_touched),
        "ready_early_count": len(ready),
        "ready_early_scored_count": len(ready_touched),
        "ready_early_reversal_precision": None if not ready_touched else len(ready_success) / len(ready_touched),
        "touch_time_candidate_coverage": _rate(episodes, "touch_candidate_available"),
        "outcome_counts": dict(Counter(str(_d(_d(e.get("primary")).get("score")).get("state") or "") for e in available)),
    }

    criteria = PASS_CRITERIA
    checks = {
        "episode_count": summary["episodes"] >= criteria["min_episode_count_each_year"],
        "candidate_coverage": (summary["primary_candidate_coverage"] or 0.0) >= criteria["min_primary_candidate_coverage"],
        "scored_touch_count": summary["scored_local_touch_count"] >= criteria["min_scored_local_touches_each_year"],
        "year_reversal_rate": (summary["reversal_050_before_invalidation_rate"] or 0.0) >= criteria["min_reversal_success_rate_each_year"],
        "ready_precision": (
            summary["ready_early_scored_count"] < 10
            or (summary["ready_early_reversal_precision"] or 0.0) >= criteria["ready_precision_floor_if_n_ge_10"]
        ),
    }
    year_pass = all(checks.values())

    payload = {
        "schema": SCHEMA,
        "year": year,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source": "HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY",
        "causal": True,
        "execution_authority": False,
        "demo_auto_execution": False,
        "live_execution_enabled": False,
        "engine_under_test": "XAU_RIZAN_SIMPLE_REVERSAL_V390",
        "primary_snapshot_offset_minutes": PRIMARY_OFFSET_MINUTES,
        "reaction_threshold_atr": REACTION_ATR,
        "pass_criteria": criteria,
        "summary": summary,
        "checks": checks,
        "year_pass": year_pass,
        "episodes": episodes,
        "limitations": [
            "This validates local zone mapping and 0.50 ATR reversal behavior, not trade profitability.",
            "Public M1 OHLC is used; this is not bid/ask tick execution replay.",
            "News/macro and transaction costs are not reconstructed in this stage.",
            "Auto-execution remains disabled regardless of this result; PF/expectancy validation is separate.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("V391_V390_YEAR_SUMMARY=" + json.dumps({"year": year, "year_pass": year_pass, "summary": summary, "checks": checks}, sort_keys=True))
    print(f"EPISODES={len(episodes)} OUTPUT={output}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.year, args.csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

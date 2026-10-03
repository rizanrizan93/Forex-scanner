from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd

import xau_v375_public_m1_replay as base
import xau_v375_public_m1_replay_fast as fast
from fx_scanner import demo_xau_v375_reaction_executor as v375


TARGET_POLICY = "STRUCTURE_FIRST_FRONT_RUN_NO_FORCED_RR"
FRONT_RUN_FRACTION = 0.10
FRONT_RUN_MAX_POINTS = 1.0


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relax_rr_only_room_blocks(evaluation: dict[str, Any]) -> None:
    """Research-only: remove RR-floor vetoes without removing proximity vetoes.

    The experiment keeps causal structure, entry logic, zone lifecycle, and the
    no-chase gates intact. It only stops forcing a >=1.50R target when the chart
    offers a nearer structural destination.
    """
    structural = dict(evaluation.get("structural_room") or {})
    if str(structural.get("state") or "") == "STRUCTURAL_RR_TOO_SMALL":
        structural["blocked"] = False
        structural["state"] = "STRUCTURAL_TARGET_ACCEPTED_WITHOUT_FORCED_RR"
        structural["research_override"] = "RR_FLOOR_ONLY"
        evaluation["structural_room"] = structural

    roadblock_room = dict(evaluation.get("roadblock_room") or {})
    if bool(roadblock_room.get("blocked")):
        nearest = dict(roadblock_room.get("nearest") or {})
        distance_parent_atr = _f(nearest.get("distance_parent_atr"))
        main_reversal = bool(nearest.get("main_reversal_eligible"))
        proximity_veto = bool(
            main_reversal
            and distance_parent_atr is not None
            and distance_parent_atr < 0.50
        )
        if not proximity_veto:
            roadblock_room["blocked"] = False
            roadblock_room["state"] = "STRUCTURAL_ROADBLOCK_ACCEPTED_WITHOUT_FORCED_RR"
            roadblock_room["research_override"] = "RR_FLOOR_ONLY"
            evaluation["roadblock_room"] = roadblock_room


def _front_run_target(
    candidate: dict[str, Any],
    evaluation: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    direction = str(candidate.get("direction") or "").upper()
    entry = _f(candidate.get("entry"))
    raw_target = _f(candidate.get("take_profit"))
    stop = _f(candidate.get("stop_loss"))
    if direction not in {"LONG", "SHORT"} or entry is None or raw_target is None or stop is None:
        return None, "STRUCTURE_TARGET_GEOMETRY_MISSING"

    source = str(candidate.get("target_source") or "UNKNOWN")
    if source == "NEAREST_ROADBLOCK":
        structure = dict(evaluation.get("nearest_roadblock") or {})
    else:
        structure = dict(evaluation.get("structural_destination") or {})

    low = _f(structure.get("low"))
    high = _f(structure.get("high"))
    width = abs(high - low) if low is not None and high is not None else 0.0
    buffer_points = min(FRONT_RUN_MAX_POINTS, FRONT_RUN_FRACTION * width)

    target = (
        raw_target - buffer_points
        if direction == "LONG"
        else raw_target + buffer_points
    )

    if direction == "LONG":
        if not (stop < entry < target):
            return None, "STRUCTURE_FRONT_RUN_NO_REWARD_ROOM"
        risk = entry - stop
        reward = target - entry
    else:
        if not (target < entry < stop):
            return None, "STRUCTURE_FRONT_RUN_NO_REWARD_ROOM"
        risk = stop - entry
        reward = entry - target
    if risk <= 0 or reward <= 0:
        return None, "STRUCTURE_FRONT_RUN_INVALID_RISK_REWARD"

    out = dict(candidate)
    out["structure_target_raw"] = raw_target
    out["take_profit"] = target
    out["structure_front_run_buffer"] = buffer_points
    out["target_policy"] = TARGET_POLICY
    out["target_source"] = f"{source}_STRUCTURE_FIRST"
    out["rr"] = reward / risk
    return out, "ELIGIBLE_STRUCTURE_FIRST_TP"


def _rr_bucket(rr: float) -> str:
    if rr < 0.50:
        return "LT_0_50"
    if rr < 1.00:
        return "0_50_TO_0_99"
    if rr < 1.50:
        return "1_00_TO_1_49"
    return "GE_1_50"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only V375 replay with TP anchored to nearest chart structure rather than a forced RR floor."
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-minutes", type=int, default=60, choices=[15, 30, 60, 120, 240])
    parser.add_argument("--spread", type=float, default=0.30)
    parser.add_argument("--entry-slippage", type=float, default=0.05)
    parser.add_argument("--stop-slippage", type=float, default=0.10)
    parser.add_argument("--cache-dir", default=".cache/xau_public_m1")
    parser.add_argument("--output", required=True)
    parser.add_argument("--trades-output", required=True)
    args = parser.parse_args()

    start = base._parse_datetime(args.start)
    end = base._parse_datetime(args.end, end=True)
    config = base.ReplayConfig(
        start=start,
        end=end,
        step_minutes=int(args.step_minutes),
        spread=float(args.spread),
        entry_slippage=float(args.entry_slippage),
        stop_slippage=float(args.stop_slippage),
        h4_bars=400,
        h1_bars=560,
        m15_bars=192,
        m5_bars=192,
        lookback_days=75,
        forward_days=90,
    )
    cache_dir = Path(args.cache_dir)

    acceleration = fast._install_replay_acceleration(config, cache_dir=cache_dir)

    original_candidate = base.v375_candidate
    source_counts: Counter[str] = Counter()
    rr_counts: Counter[str] = Counter()
    override_counts: Counter[str] = Counter()

    def structure_candidate(*, heartbeat: dict[str, Any], bid: float, ask: float, now):
        replay_heartbeat = deepcopy(heartbeat)
        evaluation = dict(dict(replay_heartbeat.get("details") or {}).get("evaluation") or {})
        _relax_rr_only_room_blocks(evaluation)
        replay_heartbeat.setdefault("details", {})["evaluation"] = evaluation

        previous_min_rr = v375.base.MIN_RR
        v375.base.MIN_RR = 0.0
        try:
            candidate, reason = v375._candidate(
                heartbeat=replay_heartbeat,
                bid=bid,
                ask=ask,
                now=now,
            )
        finally:
            v375.base.MIN_RR = previous_min_rr

        if candidate is None:
            return None, reason

        candidate, structure_reason = _front_run_target(candidate, evaluation)
        if candidate is None:
            return None, structure_reason

        source_counts[str(candidate.get("target_source") or "UNKNOWN")] += 1
        rr = _f(candidate.get("rr"))
        if rr is not None:
            rr_counts[_rr_bucket(rr)] += 1
        structural = dict(evaluation.get("structural_room") or {})
        roadblock = dict(evaluation.get("roadblock_room") or {})
        if structural.get("research_override"):
            override_counts["STRUCTURAL_RR_FLOOR"] += 1
        if roadblock.get("research_override"):
            override_counts["ROADBLOCK_RR_FLOOR"] += 1
        return candidate, structure_reason

    base.v375_candidate = structure_candidate
    try:
        metrics, trades = base.run_replay(config, cache_dir=cache_dir)
    finally:
        base.v375_candidate = original_candidate

    metrics["schema"] = "XAU_V375_STRUCTURE_FIRST_TP_REPLAY_V1"
    metrics["target_policy"] = {
        "mode": TARGET_POLICY,
        "nearest_structure_first": True,
        "forced_min_rr_removed_for_research": True,
        "proximity_veto_retained": True,
        "front_run_fraction_of_structure_width": FRONT_RUN_FRACTION,
        "front_run_cap_points": FRONT_RUN_MAX_POINTS,
        "note": "Research only; production/demo V375 is unchanged.",
    }
    metrics["replay_acceleration"] = {
        "mode": "CAUSAL_ZONE_INDEX_PLUS_FRAME_CACHE",
        **acceleration,
        "production_logic_changed": False,
    }
    metrics["target_source_counts"] = dict(source_counts)
    metrics["planned_rr_bucket_counts"] = dict(rr_counts)
    metrics["rr_floor_override_counts"] = dict(override_counts)
    metrics["lane_performance"] = {
        lane: base._metrics([trade for trade in trades if trade.execution_lane == lane])
        for lane in sorted({trade.execution_lane for trade in trades})
    }
    metrics["direction_performance"] = {
        direction: base._metrics([trade for trade in trades if trade.direction == direction])
        for direction in ("LONG", "SHORT")
        if any(trade.direction == direction for trade in trades)
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str) + "\n")

    trades_output = Path(args.trades_output)
    trades_output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(trade) for trade in trades]).to_csv(trades_output, index=False)

    print("V375_STRUCTURE_TP_RESULT=" + json.dumps(metrics, sort_keys=True, default=str), flush=True)
    print(f"RESULT_JSON={output}", flush=True)
    print(f"TRADES_CSV={trades_output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

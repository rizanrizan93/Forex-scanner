from __future__ import annotations

from math import isfinite, sqrt
from typing import Any


META_CONTRACT = "XAU_META_DECISION_CENTER_V296_1"
MIN_CALIBRATION_SAMPLE = 30


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def wilson_lower_95(wins: int, total: int) -> float | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    p = float(wins) / float(total)
    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = p + z2 / (2.0 * total)
    spread = z * sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)
    return max(0.0, (centre - spread) / denominator)


def calibrate_outcomes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = ambiguous = 0
    mfe_r: list[float] = []
    mae_r: list[float] = []
    for raw in rows:
        row = dict(raw or {})
        tp1 = bool(row.get("tp1_hit"))
        stop = bool(row.get("stop_hit"))
        if tp1 and not stop:
            wins += 1
        elif stop and not tp1:
            losses += 1
        elif row.get("outcome_class"):
            ambiguous += 1
        mfe = _f(row.get("mfe_r"))
        mae = _f(row.get("mae_r"))
        if mfe is not None:
            mfe_r.append(mfe)
        if mae is not None:
            mae_r.append(mae)

    decisive = wins + losses
    win_rate = None if decisive <= 0 else wins / decisive
    lower = wilson_lower_95(wins, decisive)
    sample_factor = _clip(decisive / MIN_CALIBRATION_SAMPLE, 0.0, 1.0)
    if decisive <= 0:
        reliability = 0.35
        state = "NO_DECISIVE_SAMPLE"
    else:
        conservative = lower if lower is not None else 0.0
        reliability = _clip(
            0.35 + 0.65 * sample_factor * (0.50 + conservative),
            0.20,
            1.15,
        )
        state = (
            "CALIBRATED"
            if decisive >= MIN_CALIBRATION_SAMPLE
            else "COLLECTING"
        )

    return {
        "wins": wins,
        "losses": losses,
        "ambiguous": ambiguous,
        "decisive": decisive,
        "win_rate": win_rate,
        "wilson_lower_95": lower,
        "sample_factor": sample_factor,
        "reliability_multiplier": reliability,
        "state": state,
        "mean_mfe_r": None if not mfe_r else sum(mfe_r) / len(mfe_r),
        "mean_mae_r": None if not mae_r else sum(mae_r) / len(mae_r),
    }


def _vote_weight(vote: dict[str, Any]) -> float:
    base = _f(vote.get("base_weight")) or 0.0
    freshness = _clip(_f(vote.get("freshness_factor")) or 0.0, 0.0, 1.0)
    calibration = dict(vote.get("calibration") or {})
    reliability = _f(calibration.get("reliability_multiplier"))
    if reliability is None:
        reliability = 0.35
    return max(0.0, base * freshness * reliability)


def _state_priority(state: str) -> int:
    return {
        "EXECUTION_READY": 5,
        "ARMED": 4,
        "SETUP_FORMING": 3,
        "WATCH": 2,
        "PREPARE": 1,
    }.get(str(state or "").upper(), 0)


def _geometry_rank(candidate: dict[str, Any]) -> tuple[float, ...]:
    calibration = dict(candidate.get("calibration") or {})
    reliability = _f(calibration.get("reliability_multiplier")) or 0.35
    score = _f(candidate.get("score")) or 0.0
    rr = _f(candidate.get("rr2"))
    if rr is None:
        rr = _f(candidate.get("rr1")) or 0.0
    authority = 1.0 if bool(candidate.get("geometry_authority")) else 0.0
    return (
        authority,
        float(_state_priority(str(candidate.get("state") or ""))),
        reliability,
        score / 100.0,
        min(max(rr, 0.0), 10.0) / 10.0,
    )


def build_meta_decision(
    *,
    votes: list[dict[str, Any]],
    geometry_candidates: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    possible_base_weight: float | None = None,
) -> dict[str, Any]:
    normalized_votes: list[dict[str, Any]] = []
    long_weight = short_weight = 0.0
    active_base = 0.0
    calibrated_active_weight = 0.0

    for raw in votes:
        vote = dict(raw or {})
        direction = str(vote.get("direction") or "").upper()
        available = bool(vote.get("available")) and direction in {"LONG", "SHORT"}
        weight = _vote_weight(vote) if available else 0.0
        if available:
            active_base += _f(vote.get("base_weight")) or 0.0
            if direction == "LONG":
                long_weight += weight
            else:
                short_weight += weight
            if str(dict(vote.get("calibration") or {}).get("state") or "") == "CALIBRATED":
                calibrated_active_weight += weight
        normalized_votes.append(
            {
                **vote,
                "direction": direction if direction in {"LONG", "SHORT"} else "ABSTAIN",
                "available": available,
                "effective_weight": weight,
            }
        )

    total_weight = long_weight + short_weight
    possible = (
        float(possible_base_weight)
        if possible_base_weight is not None and possible_base_weight > 0
        else sum(max(0.0, _f(v.get("base_weight")) or 0.0) for v in votes)
    )
    coverage = 0.0 if possible <= 0 else _clip(active_base / possible, 0.0, 1.0)

    if total_weight <= 1e-12:
        direction_score = 0.0
        agreement = 0.0
        dominant_direction = "WAIT"
        consensus = "WAIT"
    else:
        direction_score = (long_weight - short_weight) / total_weight
        agreement = max(long_weight, short_weight) / total_weight
        dominant_direction = (
            "LONG"
            if long_weight > short_weight
            else "SHORT"
            if short_weight > long_weight
            else "WAIT"
        )
        consensus = (
            "LONG"
            if direction_score >= 0.15 and agreement >= 0.58
            else "SHORT"
            if direction_score <= -0.15 and agreement >= 0.58
            else "WAIT"
        )

    evidence_coverage = (
        0.0
        if total_weight <= 0
        else _clip(calibrated_active_weight / total_weight, 0.0, 1.0)
    )
    confidence = 100.0 * (
        abs(direction_score)
        * agreement
        * sqrt(max(coverage, 0.0))
        * (0.70 + 0.30 * evidence_coverage)
    )
    confidence = _clip(confidence, 0.0, 100.0)

    hard_blocks = [
        dict(gate)
        for gate in gates
        if bool(dict(gate).get("hard_block"))
    ]
    warnings = [
        dict(gate)
        for gate in gates
        if not bool(dict(gate).get("hard_block"))
        and bool(dict(gate).get("warning"))
    ]

    complete_candidates = [
        dict(candidate)
        for candidate in geometry_candidates
        if str(dict(candidate).get("direction") or "").upper() in {"LONG", "SHORT"}
        and _f(dict(candidate).get("entry_low")) is not None
        and _f(dict(candidate).get("entry_high")) is not None
        and _f(dict(candidate).get("sl")) is not None
        and _f(dict(candidate).get("tp1")) is not None
    ]
    aligned = [
        candidate
        for candidate in complete_candidates
        if consensus in {"LONG", "SHORT"}
        and str(candidate.get("direction") or "").upper() == consensus
    ]
    aligned.sort(key=_geometry_rank, reverse=True)
    geometry = aligned[0] if aligned else {}

    reference_aligned = [
        candidate
        for candidate in complete_candidates
        if dominant_direction in {"LONG", "SHORT"}
        and str(candidate.get("direction") or "").upper() == dominant_direction
    ]
    reference_aligned.sort(key=_geometry_rank, reverse=True)
    reference_geometry = (
        reference_aligned[0]
        if reference_aligned
        else (sorted(complete_candidates, key=_geometry_rank, reverse=True)[0]
              if complete_candidates else {})
    )

    state = str(geometry.get("state") or "").upper()
    guards = list(geometry.get("active_guards") or [])
    geometry_complete = bool(geometry)
    broker_eligible = bool(
        geometry_complete
        and consensus in {"LONG", "SHORT"}
        and state == "EXECUTION_READY"
        and not guards
        and not hard_blocks
    )
    research_probe_eligible = bool(
        geometry_complete
        and consensus in {"LONG", "SHORT"}
        and state in {"ARMED", "EXECUTION_READY"}
        and not hard_blocks
        and bool(geometry.get("research_probe_eligible"))
    )

    reference_state = str(reference_geometry.get("state") or "").upper()
    conflict_research_probe_eligible = bool(
        consensus == "WAIT"
        and dominant_direction in {"LONG", "SHORT"}
        and agreement >= 0.55
        and abs(direction_score) >= 0.10
        and reference_geometry
        and str(reference_geometry.get("engine") or "") == "RIZAN_DEPTH"
        and str(reference_geometry.get("direction") or "").upper()
        == dominant_direction
        and reference_state in {"ARMED", "EXECUTION_READY"}
        and not hard_blocks
        and bool(reference_geometry.get("research_probe_eligible"))
    )

    if broker_eligible:
        action = "DEMO_ORDER_ELIGIBLE"
    elif research_probe_eligible:
        action = "DEMO_RESEARCH_PROBE_ELIGIBLE"
    elif conflict_research_probe_eligible:
        action = "DEMO_CONFLICT_RESEARCH_PROBE_ELIGIBLE"
    elif geometry_complete and consensus in {"LONG", "SHORT"}:
        action = "PREPARE_WAIT_CONFIRMATION"
    elif consensus == "WAIT":
        action = "WAIT_ENGINE_CONFLICT"
    else:
        action = "WAIT_NO_CANONICAL_GEOMETRY"

    return {
        "contract": META_CONTRACT,
        "consensus_direction": consensus,
        "dominant_direction": dominant_direction,
        "direction_score": direction_score,
        "confidence": confidence,
        "agreement": agreement,
        "coverage": coverage,
        "evidence_coverage": evidence_coverage,
        "long_weight": long_weight,
        "short_weight": short_weight,
        "active_engine_count": sum(1 for row in normalized_votes if row["available"]),
        "engine_count": len(normalized_votes),
        "votes": normalized_votes,
        "geometry": geometry,
        "reference_geometry": reference_geometry,
        "reference_geometry_execution_authority": False,
        "gates": list(gates),
        "hard_blocks": hard_blocks,
        "warnings": warnings,
        "broker_eligible": broker_eligible,
        "research_probe_eligible": research_probe_eligible,
        "conflict_research_probe_eligible": conflict_research_probe_eligible,
        "action": action,
        "execution_authority": False,
        "interpretation": (
            "V296 is a calibrated meta-decision layer. It may rank and summarize "
            "engine evidence but cannot itself authorize broker execution. Geometry "
            "is selected intact from one aligned engine; entry/SL/TP are never averaged. "
            "When consensus is WAIT, reference_geometry may still expose the best intact "
            "dominant-bias geometry. A narrowly bounded DEMO-only conflict probe may be "
            "eligible only when that exact RIZAN parent is currently aligned and all hard "
            "gates pass; it never grants production execution authority."
        ),
    }

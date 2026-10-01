from __future__ import annotations

from datetime import timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_m5_pocket_entry_replay_v314 import (
    _confirmed_opportunities,
    _limit_fill,
    _raw_entry,
    _raw_stop,
    _split,
    _times,
)
from .research_xau_precision_tp_ladder_v315 import (
    _nearest_active_opposite_h1,
    _replay_ladder,
    _summary,
)
from .research_xau_supply_demand_reaction_v183 import ZoneDestination
from .research_xau_zone_transition_ledger_v310 import build_transition_ledger

RESEARCH_VERSION = "XAU_STRUCTURAL_TP1_FRONT_RUN_V316"
ARTIFACT_CONTRACT = "XAU_STRUCTURAL_TP1_FRONT_RUN_V316_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

ENTRY_MODE = "POCKET_PROXIMAL_LIMIT"
STOP_MODE = "POCKET_DISTAL_0P10_ATR"
PARTIAL_FRACTION = 0.25
RUNNER_ATR = 1.00

TARGET_MODES = (
    "FIXED_0P15_ATR",
    "FIXED_0P20_ATR",
    "FIXED_0P25_ATR",
    "OPP_H1_FRONT_RUN_0P25_USD",
    "OPP_H1_FRONT_RUN_0P50_USD",
    "OPP_H1_FRONT_RUN_1P00_USD",
    "HYBRID_NEARER_FIXED_0P25_OR_STRUCT_0P50",
)

MIN_DEVELOPMENT_FILLS = 30
MIN_DEVELOPMENT_TP1_RATE = 0.60
MIN_DEVELOPMENT_PF = 1.10
MIN_DEVELOPMENT_AVG_R = 0.0

MIN_HOLDOUT_FILLS = 30
MIN_HOLDOUT_FILL_RATE = 0.25
MIN_HOLDOUT_TP1_RATE = 0.65
MIN_HOLDOUT_WILSON = 0.55
MIN_HOLDOUT_PRECISION = 0.55
MIN_HOLDOUT_PF = 1.30
MIN_HOLDOUT_AVG_R = 0.15


def _structural_tp1_atr(
    *,
    mode: str,
    zone: ZoneDestination,
    pocket: dict[str, Any],
    confirmation_at,
    m5_rows: Sequence[Bar],
    destinations: Sequence[ZoneDestination],
) -> tuple[float | None, dict[str, Any]]:
    direction = str(zone.direction).upper()
    sign = 1 if direction == "LONG" else -1
    raw_entry = _raw_entry(
        entry_mode=ENTRY_MODE,
        direction=direction,
        pocket=pocket,
    )
    stop = _raw_stop(
        stop_mode=STOP_MODE,
        direction=direction,
        pocket=pocket,
        zone=zone,
    )
    if raw_entry is None or stop is None:
        return None, {"state": "INVALID_ENTRY_OR_STOP"}
    times = _times(m5_rows)
    filled = _limit_fill(
        rows=m5_rows,
        times=times,
        confirmation_at=confirmation_at,
        direction=direction,
        raw_entry=float(raw_entry),
        stop=float(stop),
    )
    if filled is None:
        return None, {"state": "NO_FILL"}
    fill_index, fill, _same_bar_stop = filled
    fill_at = ensure_utc(times[fill_index])
    atr = float(zone.atr_points)
    if not isfinite(atr) or atr <= 0:
        return None, {"state": "INVALID_ATR"}

    fixed = {
        "FIXED_0P15_ATR": 0.15,
        "FIXED_0P20_ATR": 0.20,
        "FIXED_0P25_ATR": 0.25,
    }
    if mode in fixed:
        return fixed[mode], {
            "state": "FIXED_ATR",
            "fill_at": fill_at.isoformat(),
            "fill_price": float(fill),
            "target_basis": mode,
        }

    opposite = _nearest_active_opposite_h1(
        destinations=destinations,
        direction=direction,
        at=fill_at,
        price=float(fill),
    )
    if not opposite:
        return None, {
            "state": "NO_CAUSAL_OPPOSITE_H1_AT_FILL",
            "fill_at": fill_at.isoformat(),
        }
    if direction == "LONG":
        edge = float(opposite["low"])
    else:
        edge = float(opposite["high"])

    buffer = (
        0.25
        if mode == "OPP_H1_FRONT_RUN_0P25_USD"
        else 0.50
        if mode in {
            "OPP_H1_FRONT_RUN_0P50_USD",
            "HYBRID_NEARER_FIXED_0P25_OR_STRUCT_0P50",
        }
        else 1.00
    )
    structural_target = edge - buffer if direction == "LONG" else edge + buffer
    structural_atr = sign * (structural_target - float(fill)) / atr
    if structural_atr <= 0:
        return None, {
            "state": "OPPOSITE_H1_NOT_FORWARD_OF_FILL",
            "opposite_h1": opposite,
            "structural_target": structural_target,
        }

    if mode == "HYBRID_NEARER_FIXED_0P25_OR_STRUCT_0P50":
        selected_atr = min(0.25, structural_atr)
        basis = "FIXED_0P25" if 0.25 <= structural_atr else "STRUCTURAL_0P50"
    else:
        selected_atr = structural_atr
        basis = mode

    return selected_atr, {
        "state": "STRUCTURAL_TARGET_AVAILABLE",
        "fill_at": fill_at.isoformat(),
        "fill_price": float(fill),
        "opposite_h1": opposite,
        "opposite_edge": edge,
        "front_run_buffer_usd": buffer,
        "structural_target": structural_target,
        "structural_atr": structural_atr,
        "selected_tp1_atr": selected_atr,
        "target_basis": basis,
    }


def _evaluate_mode(
    opportunities: Sequence[dict[str, Any]],
    *,
    mode: str,
    zone_by_id: dict[str, ZoneDestination],
    destinations: Sequence[ZoneDestination],
    m5_rows: Sequence[Bar],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    target_available = 0
    for opportunity in opportunities:
        zone = zone_by_id.get(str(opportunity.get("selected_zone_id") or ""))
        if zone is None:
            continue
        micro = dict(opportunity.get("micro") or {})
        pocket = dict(micro.get("refined_entry_pocket") or {})
        confirmation_at = ensure_utc(
            __import__("datetime").datetime.fromisoformat(
                str(micro["confirmation_at"]).replace("Z", "+00:00")
            )
        )
        tp1_atr, target_meta = _structural_tp1_atr(
            mode=mode,
            zone=zone,
            pocket=pocket,
            confirmation_at=confirmation_at,
            m5_rows=m5_rows,
            destinations=destinations,
        )
        if tp1_atr is None:
            results.append({
                "selected_zone_id": zone.zone_id,
                "confirmation_at": confirmation_at.isoformat(),
                "state": str(target_meta.get("state") or "NO_TARGET"),
                "filled": False,
                "target_meta": target_meta,
            })
            continue
        target_available += 1
        replay = _replay_ladder(
            rows=m5_rows,
            times=_times(m5_rows),
            zone=zone,
            confirmation_at=confirmation_at,
            pocket=pocket,
            tp1_atr=float(tp1_atr),
            tp1_fraction=PARTIAL_FRACTION,
            runner_atr=RUNNER_ATR,
            destinations=destinations,
        )
        results.append({
            "selected_zone_id": zone.zone_id,
            "confirmation_at": confirmation_at.isoformat(),
            "target_mode": mode,
            "target_meta": target_meta,
            **replay,
        })

    summary = _summary(results, opportunities=len(opportunities))
    summary["target_available"] = target_available
    summary["target_availability_rate"] = (
        target_available / len(opportunities) if opportunities else None
    )
    target_distances = []
    for row in results:
        meta = dict(row.get("target_meta") or {})
        opposite = dict(meta.get("opposite_h1") or {})
        if row.get("tp1") is None or not opposite:
            continue
        target = float(row["tp1"])
        direction = str(zone_by_id.get(str(row["selected_zone_id"])).direction)
        gap = (
            max(0.0, float(opposite["low"]) - target)
            if direction == "LONG"
            else max(0.0, target - float(opposite["high"]))
        )
        target_distances.append(gap)
    summary["median_tp1_front_run_gap_usd"] = (
        median(target_distances) if target_distances else None
    )
    return {"mode": mode, "summary": summary, "results": results}


def _eligible_development(row: dict[str, Any]) -> bool:
    s = dict(row.get("summary") or {})
    pf = (
        1_000_000.0
        if bool(s.get("profit_factor_unbounded"))
        else float(s.get("profit_factor") or 0.0)
    )
    return bool(
        int(s.get("fills") or 0) >= MIN_DEVELOPMENT_FILLS
        and float(s.get("tp1_hit_rate") or 0.0) >= MIN_DEVELOPMENT_TP1_RATE
        and pf >= MIN_DEVELOPMENT_PF
        and float(s.get("avg_net_r") or -999.0) >= MIN_DEVELOPMENT_AVG_R
    )


def _select(grid: dict[str, dict[str, Any]]) -> str | None:
    ranked = []
    for mode, row in grid.items():
        if not _eligible_development(row):
            continue
        s = dict(row["summary"])
        pf = (
            1_000_000.0
            if bool(s.get("profit_factor_unbounded"))
            else float(s.get("profit_factor") or 0.0)
        )
        ranked.append((
            -float(s.get("precision_5_and_tp1_rate") or 0.0),
            -float(s.get("tp1_hit_rate") or 0.0),
            -float(s.get("avg_net_r") or 0.0),
            -pf,
            mode,
        ))
    if not ranked:
        return None
    ranked.sort()
    return str(ranked[0][-1])


def _gate(summary: dict[str, Any]) -> dict[str, Any]:
    pf = (
        1_000_000.0
        if bool(summary.get("profit_factor_unbounded"))
        else float(summary.get("profit_factor") or 0.0)
    )
    passed = bool(
        int(summary.get("fills") or 0) >= MIN_HOLDOUT_FILLS
        and float(summary.get("fill_rate") or 0.0) >= MIN_HOLDOUT_FILL_RATE
        and float(summary.get("tp1_hit_rate") or 0.0) >= MIN_HOLDOUT_TP1_RATE
        and float(summary.get("tp1_wilson_lower_95") or 0.0) >= MIN_HOLDOUT_WILSON
        and float(summary.get("precision_5_and_tp1_rate") or 0.0) >= MIN_HOLDOUT_PRECISION
        and pf >= MIN_HOLDOUT_PF
        and float(summary.get("avg_net_r") or -999.0) >= MIN_HOLDOUT_AVG_R
    )
    return {
        "passed": passed,
        "min_fills": MIN_HOLDOUT_FILLS,
        "min_fill_rate": MIN_HOLDOUT_FILL_RATE,
        "min_tp1_hit_rate": MIN_HOLDOUT_TP1_RATE,
        "min_tp1_wilson_lower_95": MIN_HOLDOUT_WILSON,
        "min_precision_5_and_tp1_rate": MIN_HOLDOUT_PRECISION,
        "min_profit_factor": MIN_HOLDOUT_PF,
        "min_avg_net_r": MIN_HOLDOUT_AVG_R,
    }


def evaluate_structural_tp1_front_run(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> dict[str, Any]:
    confirmed, zone_by_id = _confirmed_opportunities(m15_bars, m5_bars)
    destinations, _, _ = build_transition_ledger(m15_bars)
    development, holdout = _split(confirmed)

    dev_grid = {
        mode: _evaluate_mode(
            development,
            mode=mode,
            zone_by_id=zone_by_id,
            destinations=destinations,
            m5_rows=m5_bars,
        )
        for mode in TARGET_MODES
    }
    selected = _select(dev_grid)
    hold_grid = {
        mode: _evaluate_mode(
            holdout,
            mode=mode,
            zone_by_id=zone_by_id,
            destinations=destinations,
            m5_rows=m5_bars,
        )
        for mode in TARGET_MODES
    }
    selected_holdout = hold_grid.get(selected) if selected else None
    gate = (
        _gate(dict(selected_holdout.get("summary") or {}))
        if selected_holdout else {"passed": False, "reason": "NO_DEVELOPMENT_SELECTION"}
    )

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "confirmed_opportunities": len(confirmed),
        "development_opportunities": len(development),
        "holdout_opportunities": len(holdout),
        "frozen_entry": ENTRY_MODE,
        "frozen_stop": STOP_MODE,
        "partial_fraction": PARTIAL_FRACTION,
        "runner_atr": RUNNER_ATR,
        "target_modes": list(TARGET_MODES),
        "development_grid": dev_grid,
        "selected_mode": selected,
        "selected_holdout": selected_holdout,
        "holdout_gate": gate,
        "decision": (
            "HOLDOUT_GATE_PASSED_FORWARD_DEMO_SHADOW_NEXT"
            if bool(gate.get("passed"))
            else "HOLDOUT_GATE_NOT_PASSED"
        ),
        "limitations": [
            "RECENT_ERA_STAGE4_REANALYSIS_NOT_EXTERNAL_OOS",
            "OPPOSITE_H1_MUST_BE_CAUSALLY_ACTIVE_AT_FILL",
            "FIXED_COST_PROXY_AND_M5_OHLC_STOP_FIRST",
            "NO_EXECUTION_OR_PROMOTION_AUTHORITY",
        ],
    }

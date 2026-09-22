from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_afic_displacement_origin_v154 import _published_round_target, _zone_stop
from .research_xau_afic_h4_map_selector_v161 import (
    PRIMARY_SELECTOR,
    WINDOWS,
    _records,
    _selected,
)
from .research_xau_afic_planb_remap_v159 import (
    CONFIRM_WINDOW_M15,
    _second_leg_outcome,
    _touch,
    _zone_invalidated,
)
from .research_xau_afic_public_path_state_v155 import _m15_engulfing_rejection

RESEARCH_VERSION = "XAU_AFIC_M15_CONFIRM_SEMANTICS_V165"
ARTIFACT_CONTRACT = "XAU_AFIC_M15_CONFIRM_SEMANTICS_V165_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

CONTROL_RULE = "STRICT_ENGULF_REJECT"
RULES = (
    CONTROL_RULE,
    "DIRECTIONAL_REJECTION",
    "SWEEP_RECLAIM",
)
RULE_EVIDENCE = {
    "STRICT_ENGULF_REJECT": "PUBLIC_EXAMPLE_STRONG_CONFIRMATION_CONTROL",
    "DIRECTIONAL_REJECTION": "PUBLIC_REJECTION_WORDING_DIAGNOSTIC",
    "SWEEP_RECLAIM": "SMC_ICT_RECONSTRUCTION_INFERENCE_DIAGNOSTIC",
}


def _directional_rejection(rows: Sequence[Bar], i: int, zone: Any) -> bool:
    if i < 0:
        return False
    row = rows[i]
    if not _touch(row, zone):
        return False
    o = float(row.open)
    c = float(row.close)
    if zone.direction == "SHORT":
        return bool(c < o and c <= float(zone.low))
    return bool(c > o and c >= float(zone.high))


def _sweep_reclaim(rows: Sequence[Bar], i: int, zone: Any) -> bool:
    if i < 0:
        return False
    row = rows[i]
    if not _touch(row, zone):
        return False
    if zone.direction == "SHORT":
        return bool(float(row.high) > float(zone.high) and float(row.close) <= float(zone.high))
    return bool(float(row.low) < float(zone.low) and float(row.close) >= float(zone.low))


def _rule_fires(rows: Sequence[Bar], i: int, zone: Any, rule: str) -> bool:
    if rule == CONTROL_RULE:
        return bool(_m15_engulfing_rejection(rows, i, zone))
    if rule == "DIRECTIONAL_REJECTION":
        return _directional_rejection(rows, i, zone)
    if rule == "SWEEP_RECLAIM":
        return _sweep_reclaim(rows, i, zone)
    raise ValueError(f"V165_UNKNOWN_RULE:{rule}")


def _find_confirmation(rows: Sequence[Bar], scenario: Any, rule: str) -> int | None:
    touch_i = scenario.first_touch_index
    if touch_i is None:
        return None
    end_i = min(len(rows) - 2, int(touch_i) + CONFIRM_WINDOW_M15)
    for i in range(int(touch_i), end_i + 1):
        if _zone_invalidated(rows[i], scenario.zone):
            return None
        if _rule_fires(rows, i, scenario.zone, rule):
            return i
    return None


def _outcome_from_confirmation(
    rows: Sequence[Bar], scenario: Any, confirm_i: int
) -> dict[str, Any]:
    entry_i = int(confirm_i) + 1
    if entry_i >= len(rows):
        return {
            "geometry_feasible": False,
            "tp1_hit": None,
            "terminal_hit": None,
            "stop_hit": None,
            "resolved": "NO_NEXT_BAR",
            "entry_delay_bars": int(confirm_i) - int(scenario.first_touch_index),
        }

    entry = float(rows[entry_i].open)
    stop = float(_zone_stop(scenario.zone))
    target = _published_round_target(entry, stop, scenario.continuation_direction)
    if target is None:
        return {
            "geometry_feasible": False,
            "tp1_hit": None,
            "terminal_hit": None,
            "stop_hit": None,
            "resolved": "NO_TARGET_GEOMETRY",
            "entry_delay_bars": int(confirm_i) - int(scenario.first_touch_index),
            "entry": entry,
            "stop": stop,
        }

    _, terminal, ladder = target
    if not ladder:
        return {
            "geometry_feasible": False,
            "tp1_hit": None,
            "terminal_hit": None,
            "stop_hit": None,
            "resolved": "NO_TARGET_LADDER",
            "entry_delay_bars": int(confirm_i) - int(scenario.first_touch_index),
            "entry": entry,
            "stop": stop,
        }

    alt = replace(
        scenario,
        confirm_at=ensure_utc(rows[confirm_i].timestamp),
        confirm_index=int(confirm_i),
        entry_at=ensure_utc(rows[entry_i].timestamp),
        entry=entry,
        stop=stop,
        tp1=float(ladder[0]),
        terminal=float(terminal),
        primary_status="CONFIRMED",
        failure_at=None,
        failure_reason=None,
    )
    outcome = _second_leg_outcome(f=alt, bars=rows, confirm_index=int(confirm_i))
    return {
        "geometry_feasible": True,
        "tp1_hit": bool(outcome["tp1_hit"]),
        "terminal_hit": bool(outcome["terminal_hit"]),
        "stop_hit": bool(outcome["stop_hit"]),
        "resolved": str(outcome["resolved"]),
        "entry_delay_bars": int(confirm_i) - int(scenario.first_touch_index),
        "entry": entry,
        "stop": stop,
        "tp1": float(ladder[0]),
        "terminal": float(terminal),
    }


def _selected_window(records: Sequence[Any], start: datetime, end: datetime):
    return tuple(
        x
        for x in records
        if ensure_utc(start) <= ensure_utc(x[0].map_at) < ensure_utc(end)
        and _selected(x[1], PRIMARY_SELECTOR)
    )


def _evaluate_rule(rows: Sequence[Bar], selected: Sequence[Any], rule: str):
    out = []
    for scenario, _features, _control_outcome in selected:
        if scenario.first_touch_index is None:
            continue
        confirm_i = _find_confirmation(rows, scenario, rule)
        if confirm_i is None:
            continue
        outcome = _outcome_from_confirmation(rows, scenario, confirm_i)
        out.append(
            {
                "map_at": ensure_utc(scenario.map_at).isoformat(),
                "direction": scenario.continuation_direction,
                "confirm_index": int(confirm_i),
                **outcome,
            }
        )
    return tuple(out)


def _summarize(
    rows: Sequence[Bar],
    records: Sequence[Any],
    start: datetime,
    end: datetime,
    rule: str,
) -> dict[str, Any]:
    selected = _selected_window(records, start, end)
    touched = tuple(x for x in selected if x[0].first_touch_index is not None)
    evaluated = _evaluate_rule(rows, selected, rule)
    feasible = tuple(x for x in evaluated if x["geometry_feasible"])
    delays = [int(x["entry_delay_bars"]) for x in evaluated]

    return {
        "selector": PRIMARY_SELECTOR,
        "confirmation_rule": rule,
        "evidence_class": RULE_EVIDENCE[rule],
        "scenarios": len(selected),
        "first_leg_zone_hits": len(touched),
        "first_leg_zone_hit_rate": None if not selected else len(touched) / len(selected),
        "confirmation_count": len(evaluated),
        "confirmation_rate_given_hit": None if not touched else len(evaluated) / len(touched),
        "geometry_feasible_count": len(feasible),
        "geometry_feasible_rate_given_confirm": None if not evaluated else len(feasible) / len(evaluated),
        "tp1_rate_given_confirm": None
        if not evaluated
        else sum(bool(x["tp1_hit"]) for x in evaluated if x["tp1_hit"] is not None) / len(evaluated),
        "tp1_rate_given_feasible": None
        if not feasible
        else sum(bool(x["tp1_hit"]) for x in feasible) / len(feasible),
        "terminal_rate_given_feasible": None
        if not feasible
        else sum(bool(x["terminal_hit"]) for x in feasible) / len(feasible),
        "stop_rate_given_feasible": None
        if not feasible
        else sum(bool(x["stop_hit"]) for x in feasible) / len(feasible),
        "median_confirmation_delay_bars": None if not delays else float(median(delays)),
        "direction_counts": {
            "CONT_LONG": sum(x["direction"] == "LONG" for x in evaluated),
            "CONT_SHORT": sum(x["direction"] == "SHORT" for x in evaluated),
        },
    }


def _overlap(
    rows: Sequence[Bar],
    records: Sequence[Any],
    start: datetime,
    end: datetime,
    candidate_rule: str,
) -> dict[str, int]:
    selected = _selected_window(records, start, end)
    touched_maps = {
        ensure_utc(s.map_at).isoformat()
        for s, _features, _outcome in selected
        if s.first_touch_index is not None
    }
    control = {x["map_at"] for x in _evaluate_rule(rows, selected, CONTROL_RULE)}
    candidate = {x["map_at"] for x in _evaluate_rule(rows, selected, candidate_rule)}
    return {
        "both": len(control & candidate),
        "candidate_only": len(candidate - control),
        "control_only": len(control - candidate),
        "neither": len(touched_maps - (control | candidate)),
    }


def evaluate_v165(rows: Sequence[Bar], *, evaluation_end) -> dict[str, Any]:
    end = ensure_utc(evaluation_end)
    bars, records = _records(rows, end)

    windows: dict[str, Any] = {}
    for label, start, stop in WINDOWS:
        bounded_stop = min(ensure_utc(stop), end)
        if ensure_utc(start) >= bounded_stop:
            continue
        windows[label] = {
            "rules": {
                rule: _summarize(bars, records, start, bounded_stop, rule)
                for rule in RULES
            },
            "overlap_vs_control": {
                rule: _overlap(bars, records, start, bounded_stop, rule)
                for rule in RULES
                if rule != CONTROL_RULE
            },
        }

    full_start = datetime(2012, 1, 1, tzinfo=timezone.utc)
    full = {
        "rules": {
            rule: _summarize(bars, records, full_start, end, rule)
            for rule in RULES
        },
        "overlap_vs_control": {
            rule: _overlap(bars, records, full_start, end, rule)
            for rule in RULES
            if rule != CONTROL_RULE
        },
    }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "matched_map_contract": "V161_PRIMARY_SELECTOR_MAPS_ONLY",
        "selector_contract": {
            "primary_selector": PRIMARY_SELECTOR,
            "zone_distance_atr_max": 0.75,
            "directional_close_location_max": 0.65,
            "unchanged_from_v161": True,
        },
        "confirmation_contract": {
            "control": CONTROL_RULE,
            "rules": list(RULES),
            "confirm_window_m15_bars": CONFIRM_WINDOW_M15,
            "no_threshold_grid": True,
            "no_same_sample_promotion": True,
            "public_evidence_interpretation": [
                "M15 is the public confirmation timeframe.",
                "Bearish engulfing after rejection is a strong confirmation example.",
                "Public wording also says to wait for rejection in the zone before entry.",
                "Sweep/reclaim is SMC/ICT reconstruction inference, not a verified AFIC rule.",
            ],
        },
        "full": full,
        "windows": windows,
        "note": (
            "V165 is a matched-map diagnostic of M15 confirmation semantics. "
            "It does not alter H4 map selection, reaction zones, execution authority, "
            "or promote any confirmation rule."
        ),
    }

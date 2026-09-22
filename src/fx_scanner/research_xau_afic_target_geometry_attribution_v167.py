from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_afic_displacement_origin_v154 import (
    MAX_LADDER_STEPS,
    MIN_PUBLISHED_RR,
    TP_LADDER_STEP_USD,
)
from .research_xau_afic_h4_map_selector_v161 import WINDOWS
from .research_xau_afic_independent_path_confirm_v166 import (
    RULES,
    build_independent_rule_path,
)

RESEARCH_VERSION = "XAU_AFIC_TARGET_GEOMETRY_ATTRIBUTION_V167"
ARTIFACT_CONTRACT = "XAU_AFIC_TARGET_GEOMETRY_ATTRIBUTION_V167_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
LIVE_EXECUTION_ENABLED = False

MAX_DISPLAY_DISTANCE_USD = float(MAX_LADDER_STEPS) * float(TP_LADDER_STEP_USD)
MAX_RISK_USD_FOR_FULL_LADDER = MAX_DISPLAY_DISTANCE_USD / float(MIN_PUBLISHED_RR)

FEASIBLE = "FEASIBLE"
INVALID_RISK = "INVALID_RISK"
RISK_GT_DISPLAY_CAP = "RISK_GT_7_STEP_1P5R_CAP"
ROUND_LADDER_TRUNCATION = "ROUND_LADDER_TRUNCATION"


def geometry_failure_class(scenario: Any) -> str:
    if scenario.confirm_index is None:
        raise ValueError("V167_REQUIRES_RAW_CONFIRMATION")
    if scenario.entry is None or scenario.stop is None:
        return INVALID_RISK

    risk = abs(float(scenario.entry) - float(scenario.stop))
    if risk <= 0:
        return INVALID_RISK
    if scenario.primary_status == "CONFIRMED":
        return FEASIBLE
    if risk > MAX_RISK_USD_FOR_FULL_LADDER + 1e-12:
        return RISK_GT_DISPLAY_CAP
    return ROUND_LADDER_TRUNCATION


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    x = sorted(float(v) for v in values)
    if len(x) == 1:
        return x[0]
    pos = (len(x) - 1) * float(q)
    lo = int(pos)
    hi = min(len(x) - 1, lo + 1)
    frac = pos - lo
    return x[lo] * (1.0 - frac) + x[hi] * frac


def _summary(scenarios: Sequence[Any], start: datetime, end: datetime) -> dict[str, Any]:
    start = ensure_utc(start)
    end = ensure_utc(end)
    ss = tuple(
        s for s in scenarios
        if start <= ensure_utc(s.map_at) < end and s.confirm_index is not None
    )

    rows = []
    for s in ss:
        risk = None
        if s.entry is not None and s.stop is not None:
            risk = abs(float(s.entry) - float(s.stop))
        rows.append((s, risk, geometry_failure_class(s)))

    valid_risks = [float(risk) for _, risk, _ in rows if risk is not None and risk > 0]
    feasible = [x for x in rows if x[2] == FEASIBLE]
    no_geometry = [x for x in rows if x[2] != FEASIBLE]
    wide = [x for x in rows if x[2] == RISK_GT_DISPLAY_CAP]
    trunc = [x for x in rows if x[2] == ROUND_LADDER_TRUNCATION]
    invalid = [x for x in rows if x[2] == INVALID_RISK]

    return {
        "raw_confirmation_count": len(rows),
        "geometry_feasible_count": len(feasible),
        "geometry_feasible_rate": None if not rows else len(feasible) / len(rows),
        "no_geometry_count": len(no_geometry),
        "no_geometry_rate": None if not rows else len(no_geometry) / len(rows),
        "failure_counts": {
            RISK_GT_DISPLAY_CAP: len(wide),
            ROUND_LADDER_TRUNCATION: len(trunc),
            INVALID_RISK: len(invalid),
        },
        "failure_share_of_no_geometry": {
            RISK_GT_DISPLAY_CAP: None if not no_geometry else len(wide) / len(no_geometry),
            ROUND_LADDER_TRUNCATION: None if not no_geometry else len(trunc) / len(no_geometry),
            INVALID_RISK: None if not no_geometry else len(invalid) / len(no_geometry),
        },
        "risk_usd": {
            "n": len(valid_risks),
            "p25": _percentile(valid_risks, 0.25),
            "median": None if not valid_risks else float(median(valid_risks)),
            "p75": _percentile(valid_risks, 0.75),
            "max": None if not valid_risks else max(valid_risks),
            "share_gt_exact_cap": None
            if not valid_risks
            else sum(x > MAX_RISK_USD_FOR_FULL_LADDER for x in valid_risks)
            / len(valid_risks),
        },
        "direction_counts": {
            "LONG": sum(s.continuation_direction == "LONG" for s, _, _ in rows),
            "SHORT": sum(s.continuation_direction == "SHORT" for s, _, _ in rows),
        },
    }


def evaluate_v167(rows: Sequence[Bar], *, evaluation_end: datetime) -> dict[str, Any]:
    end = ensure_utc(evaluation_end)
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))

    paths = {
        rule: build_independent_rule_path(
            bars,
            evaluation_end=end,
            rule=rule,
        )[0]
        for rule in RULES
    }

    full_start = datetime(2012, 1, 1, tzinfo=timezone.utc)
    full = {
        rule: _summary(paths[rule], full_start, end)
        for rule in RULES
    }

    windows: dict[str, Any] = {}
    for label, start, stop in WINDOWS:
        bounded_stop = min(ensure_utc(stop), end)
        if ensure_utc(start) >= bounded_stop:
            continue
        windows[label] = {
            rule: _summary(paths[rule], start, bounded_stop)
            for rule in RULES
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "rules": list(RULES),
        "geometry_contract": {
            "tp_ladder_step_usd": float(TP_LADDER_STEP_USD),
            "max_ladder_steps": int(MAX_LADDER_STEPS),
            "max_display_distance_usd": MAX_DISPLAY_DISTANCE_USD,
            "min_published_rr": float(MIN_PUBLISHED_RR),
            "exact_max_risk_usd_if_all_7_steps_available":
                MAX_RISK_USD_FOR_FULL_LADDER,
            "identity": "7*3 / 1.5 = 14 USD maximum structural risk",
            "no_parameter_change": True,
        },
        "classification_contract": {
            FEASIBLE: "Existing frozen V154 target geometry returns a published ladder.",
            RISK_GT_DISPLAY_CAP: (
                "Structural risk exceeds exact mathematical capacity of a seven-step "
                "$3 ladder at minimum 1.5R."
            ),
            ROUND_LADDER_TRUNCATION: (
                "Risk is within the exact $14 cap, but psychological-front placement "
                "and $3 ladder truncation still leave displayed terminal below 1.5R."
            ),
            INVALID_RISK: "Missing/non-positive historical entry-stop risk.",
        },
        "full": full,
        "windows": windows,
        "note": (
            "V167 attributes existing target-geometry rejection only. It does not "
            "increase TP count, alter stop geometry, retune RR, or change execution."
        ),
    }

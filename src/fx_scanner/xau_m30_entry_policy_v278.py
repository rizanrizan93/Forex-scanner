from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT = "XAU_M30_ENTRY_POLICY_V278"
POLICY_EFFECT = "DEMO_CALIBRATION_LABEL_ONLY"
EXECUTION_AUTHORITY = False
_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "calibration"
    / "xau_v278_m30_entry_policy.json"
)


def load_v278_evidence() -> dict[str, Any]:
    return json.loads(_EVIDENCE_PATH.read_text())


def evaluate_m30_entry_policy_v278(
    *,
    deep_rejection: dict[str, Any],
    m30_shadow: dict[str, Any],
    composite_pressure: dict[str, Any],
    direction: str,
) -> dict[str, Any]:
    evidence = load_v278_evidence()
    side = str(direction or "").upper()
    key = "nearest_supply" if side == "SHORT" else "nearest_demand"
    parent = dict(m30_shadow.get(key) or {}) if side in {"LONG", "SHORT"} else {}
    overlap = float(parent.get("canonical_overlap_ratio") or 0.0)
    rejection_state = str(deep_rejection.get("state") or "UNAVAILABLE")
    composite_available = bool(composite_pressure.get("available"))
    composite_allowed = bool(
        composite_pressure.get(
            "short_calibration_allowed"
            if side == "SHORT"
            else "long_calibration_allowed"
            if side == "LONG"
            else "",
            False,
        )
    )

    if rejection_state == "PARENT_INVALIDATED":
        lane_state = "SETUP_INVALID"
        lane = "NONE"
    elif rejection_state == "DEEP_REJECTION_CONFIRMED":
        lane_state = "RECOVERY_WATCH"
        lane = "DEEP_REJECTION_SECONDARY"
    elif rejection_state in {"AHEAD_OF_PARENT_ZONE", "SHALLOW_OR_MID_TOUCH"}:
        lane_state = "PRIMARY_NEAR_EDGE_ACTIVE"
        lane = "NEAR_EDGE_FIRST_TOUCH"
    elif rejection_state == "DEEP_TOUCH_WAIT_REJECTION":
        lane_state = "WAIT_DEEP_REJECTION"
        lane = "NONE"
    else:
        lane_state = "WAIT"
        lane = "NONE"

    return {
        "contract": CONTRACT,
        "execution_authority": EXECUTION_AUTHORITY,
        "policy_effect": POLICY_EFFECT,
        "direction": side or None,
        "lane": lane,
        "lane_state": lane_state,
        "m30_parent_overlap_ratio": overlap,
        "high_overlap": overlap >= 0.70,
        "composite_pressure_available": composite_available,
        "composite_direction_allowed": composite_allowed,
        "research_evidence": {
            "history_closed_m15_bars": evidence["history_closed_m15_bars"],
            "episodes": evidence["episodes"],
            "holdout_n": evidence["holdout_n"],
            "near_edge_hold_050_same_confirmed_population": evidence[
                "holdout_near_edge_hold_050_same_confirmed_population"
            ],
            "deep_rejection_hold_050_rate": evidence[
                "holdout_deep_rejection_hold_050_rate"
            ],
            "delta": evidence["holdout_confirmation_minus_near_edge_delta"],
            "median_max_depth_confirmed": evidence[
                "holdout_median_max_depth_confirmed"
            ],
            "median_confirmation_depth": evidence[
                "holdout_median_confirmation_depth"
            ],
            "median_confirmation_retreat": evidence[
                "holdout_median_confirmation_retreat"
            ],
            "high_overlap": dict(evidence["holdout_high_overlap"]),
        },
        "policy": dict(evidence["policy_interpretation"]),
        "note": (
            "V278 keeps near-edge first-touch as the primary DEMO calibration lane because "
            "the frozen holdout showed a higher >=0.50 ATR reaction rate on the same "
            "deep-rejection-confirmed population. Deep rejection remains a secondary "
            "recovery/re-entry watch, never an extra simultaneous exposure."
        ),
    }

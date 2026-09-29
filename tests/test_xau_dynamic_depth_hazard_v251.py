from fx_scanner.xau_dynamic_depth_hazard_v251 import (
    build_dynamic_depth_hazard,
    build_geometry_depth_status,
    child_reference_depth,
    normalized_depth,
)


def _v226():
    bands = [
        {"band":"00-10%","lower_depth":0.0,"upper_depth":0.1,"hazard":0.20,"wilson_lower_95":0.15,"at_risk":500},
        {"band":"10-20%","lower_depth":0.1,"upper_depth":0.2,"hazard":0.16,"wilson_lower_95":0.12,"at_risk":400},
        {"band":"20-30%","lower_depth":0.2,"upper_depth":0.3,"hazard":0.14,"wilson_lower_95":0.10,"at_risk":300},
        {"band":"30-40%","lower_depth":0.3,"upper_depth":0.4,"hazard":0.13,"wilson_lower_95":0.09,"at_risk":250},
    ]
    return {
        "focus_direction":"LONG",
        "depth_entry_candidate":{"source_layer":"M15_NESTED_LOCATOR"},
        "long":{
            "m15":{
                "zone":{"direction":"LONG","low":100.0,"high":110.0},
                "standalone_profile_context":{"touches":1500,"hazard_bands":bands},
            }
        }
    }


def test_normalized_depth_mirrors_zone_geometry():
    assert normalized_depth({"direction":"LONG","low":100,"high":110}, 108) == 0.2
    assert normalized_depth({"direction":"SHORT","low":100,"high":110}, 102) == 0.2


def test_reacceleration_waits_deeper_than_current_band():
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=109.5,
        pressure_transition={
            "state":"OPPOSING_REACCELERATION",
            "hard_block":True,
            "pre_touch_entry_allowed":False,
            "confirmation_entry_allowed":False,
        },
    )
    assert result["state"] == "DYNAMIC_DEPTH_HAZARD_AVAILABLE"
    assert result["recommended_depth_low"] >= 0.10
    assert result["action"] == "WAIT_PRESSURE"
    assert result["execution_ready"] is False


def test_absorption_can_use_current_hazard_window():
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=109.5,
        pressure_transition={
            "state":"BALANCED_ABSORPTION",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["recommended_depth_low"] == 0.0
    assert result["action"] == "ENTRY_WINDOW"
    assert result["execution_ready"] is True


def test_child_reference_depth_uses_source_zone():
    assert child_reference_depth(
        v226_evaluation=_v226(),
        direction="LONG",
        price=107.0,
    ) == 0.3


def test_absorption_ahead_of_zone_waits_for_zone():
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=112.0,
        pressure_transition={
            "state":"BALANCED_ABSORPTION",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["location_state"] == "AHEAD_OF_ZONE"
    assert result["action"] == "WAIT_ZONE"
    assert result["execution_ready"] is False


def test_absorption_beyond_distal_requires_remap():
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=99.0,
        pressure_transition={
            "state":"CONTROL_FLIP",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["location_state"] == "AT_OR_BEYOND_DISTAL"
    assert result["action"] == "WAIT_STRUCTURE_REMAP"
    assert result["execution_ready"] is False



def test_geometry_only_depth_marks_touched_zone_after_reaction() -> None:
    zone = {
        "direction": "LONG",
        "timeframe": "H1",
        "low": 100.0,
        "high": 110.0,
        "touch_count": 1,
    }
    result = build_geometry_depth_status(zone=zone, live_price=112.0)
    assert result["state"] == "GEOMETRY_ONLY"
    assert result["location_state"] == "AFTER_REACTION"
    assert result["action"] == "WAIT_NEW_TRIGGER"
    assert result["recommended_depth_low"] is None
    assert result["execution_ready"] is False


def test_geometry_only_depth_ahead_if_zone_never_touched() -> None:
    zone = {
        "direction": "LONG",
        "timeframe": "H1",
        "low": 100.0,
        "high": 110.0,
        "touch_count": 0,
    }
    result = build_geometry_depth_status(zone=zone, live_price=112.0)
    assert result["location_state"] == "AHEAD_OF_ZONE"
    assert result["action"] == "WAIT_ZONE"


def test_geometry_only_depth_reports_physical_depth_without_hazard_prior() -> None:
    zone = {
        "direction": "LONG",
        "timeframe": "H1",
        "low": 100.0,
        "high": 110.0,
        "touch_count": 1,
    }
    result = build_geometry_depth_status(zone=zone, live_price=107.0)
    assert result["location_state"] == "INSIDE_ZONE"
    assert result["current_depth"] == 0.3
    assert result["recommended_band"] == {}
    assert result["historical_prior_scope"] == "GEOMETRY_ONLY_NO_CALIBRATED_PRIOR"

def test_dynamic_depth_rejects_opposite_v226_focus_direction() -> None:
    payload = _v226()
    payload["focus_direction"] = "SHORT"
    result = build_dynamic_depth_hazard(
        v226_evaluation=payload,
        direction="LONG",
        live_price=107.0,
        pressure_transition={
            "state": "BALANCED_ABSORPTION",
            "hard_block": False,
            "pre_touch_entry_allowed": True,
            "confirmation_entry_allowed": True,
        },
    )
    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == "V226_FOCUS_DIRECTION_MISMATCH"
    assert result["execution_ready"] is False


def test_dynamic_depth_rejects_opposite_candidate_direction() -> None:
    payload = _v226()
    payload["depth_entry_candidate"]["direction"] = "SHORT"
    result = build_dynamic_depth_hazard(
        v226_evaluation=payload,
        direction="LONG",
        live_price=107.0,
        pressure_transition={
            "state": "BALANCED_ABSORPTION",
            "hard_block": False,
            "pre_touch_entry_allowed": True,
            "confirmation_entry_allowed": True,
        },
    )
    assert result["state"] == "UNAVAILABLE"
    assert result["reason"] == "V226_CANDIDATE_DIRECTION_MISMATCH"
    assert result["execution_ready"] is False



def test_v261_dynamic_depth_uses_active_v182_local_source_profile() -> None:
    bands = [
        {"band": "00-20%", "lower_depth": 0.0, "upper_depth": 0.2, "hazard": 0.20, "wilson_lower_95": 0.15, "at_risk": 300},
        {"band": "20-40%", "lower_depth": 0.2, "upper_depth": 0.4, "hazard": 0.25, "wilson_lower_95": 0.18, "at_risk": 240},
        {"band": "40-60%", "lower_depth": 0.4, "upper_depth": 0.6, "hazard": 0.18, "wilson_lower_95": 0.12, "at_risk": 180},
    ]
    source = {
        "zone_id": "current-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 100.0,
        "high": 110.0,
        "lifecycle": {"active": True, "touch_count": 3},
    }
    payload = {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "source_layer": "V182_ACTIVE_H1_HISTORICAL_HOTSPOT",
            "source_timeframe": "H1",
            "source_zone": source,
            "source_profile": {"touches": 1200, "hazard_bands": bands},
            "retest_confirmation_eligible": True,
            "zone_reuse": {
                "historical_prior_scope": "FIRST_TOUCH_PRIOR_GEOMETRY_ONLY",
                "h1_touch_count": 3,
            },
        },
        "short": {},
    }

    result = build_dynamic_depth_hazard(
        v226_evaluation=payload,
        direction="SHORT",
        live_price=103.0,
        pressure_transition={
            "state": "BALANCED_ABSORPTION",
            "hard_block": False,
            "pre_touch_entry_allowed": False,
            "confirmation_entry_allowed": True,
        },
    )

    assert result["state"] == "DYNAMIC_DEPTH_HAZARD_AVAILABLE"
    assert result["timeframe"] == "H1"
    assert result["source_zone"]["zone_id"] == "current-h1-supply"
    assert result["historical_prior_scope"] == "FIRST_TOUCH_PRIOR_GEOMETRY_ONLY"
    assert result["retest_confirmation_required"] is True
    assert result["execution_ready"] is True


def test_v269_probe_depth_is_separate_from_strict_execution_ready(monkeypatch) -> None:
    monkeypatch.setenv("CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH", "0.70")
    payload = _v226()
    payload["long"]["m15"]["standalone_profile_context"]["hazard_bands"] = [
        {
            "band": f"{i * 10:02d}-{(i + 1) * 10:02d}%",
            "lower_depth": i / 10,
            "upper_depth": (i + 1) / 10,
            "hazard": 0.20 - i * 0.01,
            "wilson_lower_95": 0.10,
            "at_risk": 500 - i * 20,
        }
        for i in range(10)
    ]
    result = build_dynamic_depth_hazard(
        v226_evaluation=payload,
        direction="LONG",
        live_price=102.0,
        pressure_transition={
            "state":"BALANCED_ABSORPTION",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["current_depth"] == 0.8
    assert result["action"] == "ENTRY_WINDOW"
    assert result["execution_ready"] is True
    assert result["calibration_probe_depth_ceiling"] == 0.70
    assert result["calibration_probe_depth_eligible"] is False
    assert result["calibration_probe_depth_action"] == "NO_CHASE_DEEP_ZONE"


def test_v269_probe_depth_is_eligible_when_not_too_deep(monkeypatch) -> None:
    monkeypatch.setenv("CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH", "0.70")
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=107.0,
        pressure_transition={
            "state":"BALANCED_ABSORPTION",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["current_depth"] == 0.3
    assert result["calibration_probe_depth_eligible"] is True
    assert result["calibration_probe_depth_action"] == "ELIGIBLE_BY_DEPTH_ONLY"


def test_v269_probe_depth_ceiling_env_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("CTRADER_DEMO_DEPTH_CALIBRATION_PROBE_MAX_DEPTH", "1.50")
    result = build_dynamic_depth_hazard(
        v226_evaluation=_v226(),
        direction="LONG",
        live_price=107.0,
        pressure_transition={
            "state":"BALANCED_ABSORPTION",
            "hard_block":False,
            "pre_touch_entry_allowed":True,
            "confirmation_entry_allowed":True,
        },
    )
    assert result["calibration_probe_depth_ceiling"] == 1.0

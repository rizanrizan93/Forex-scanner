from datetime import datetime,timezone

from fx_scanner.demo_xau_afic_prepared_plan_producer import (
    EXECUTION_STRATEGY_ID,MAX_H4_DIRECTIONAL_CLOSE_LOC,MAX_ZONE_DISTANCE_ATR,
    STATE_CODE,STATE_EVENT_TYPE,STRATEGY_ID,confirmation_latency_seconds,
    entry_drift_metrics,forecast_state_key,prepared_blueprint,
    prepared_observability,selector_grade,signal_state_and_guards,zone_proximity
)

UTC=timezone.utc

def test_afic_prepared_identity_and_selector():
    assert STRATEGY_ID=="XAU_AFIC_PATH_PREPARED_V1"
    assert EXECUTION_STRATEGY_ID=="XAU_AFIC_PATH_EXECUTION_V1"
    assert MAX_ZONE_DISTANCE_ATR==0.75
    assert MAX_H4_DIRECTIONAL_CLOSE_LOC==0.65
    assert selector_grade({"zone_distance_atr":0.4,"h4_directional_close_location":0.55})=="A"
    assert selector_grade({"zone_distance_atr":0.4,"h4_directional_close_location":0.90})=="B"
    assert selector_grade({"zone_distance_atr":1.1,"h4_directional_close_location":0.40})=="C"

def test_afic_prepared_short_blueprint_is_structural():
    payload={
        "continuation_direction":"SHORT",
        "zone":{"low":4350.0,"high":4359.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.4,"h4_directional_close_location":0.55},
    }
    plan=prepared_blueprint(payload)
    assert plan is not None
    assert plan["entry"]==4350.0
    assert plan["stop"]==4360.0
    assert plan["selector_grade"]=="A"
    assert plan["tp2"]<plan["entry"]
    assert plan["rr2"]>=1.5
    assert plan["confirmation_required"]=="M15_ENGULF_REJECTION"

def test_afic_prepared_long_blueprint_is_structural():
    payload={
        "continuation_direction":"LONG",
        "zone":{"low":4320.0,"high":4325.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.5,"h4_directional_close_location":0.60},
    }
    plan=prepared_blueprint(payload)
    assert plan is not None
    assert plan["entry"]==4325.0
    assert plan["stop"]==4319.0
    assert plan["tp2"]>plan["entry"]
    assert plan["rr2"]>=1.5

def test_afic_confirmation_latency_uses_completed_m15_boundary():
    payload={"confirm_at":"2026-09-21T12:00:00+00:00"}
    detected=datetime(2026,9,21,12,15,42,tzinfo=UTC)
    assert confirmation_latency_seconds(payload,detected_at=detected)==42.0

def test_afic_entry_drift_is_normalized_by_prepared_risk():
    prepared={"entry":4350.0,"stop":4360.0}
    live={"entry":4349.0}
    x=entry_drift_metrics(prepared=prepared,live=live)
    assert x["entry_drift_abs"]==1.0
    assert x["entry_drift_r"]==0.1


def test_afic_prepared_observability_explains_missing_forecast_geometry():
    payload={
        "state":"APPROACHING_ZONE",
        "map_at":"2026-09-22T00:00:00+00:00",
        "continuation_direction":"SHORT",
        "zone":{"low":4350.0,"high":4359.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.4,"h4_directional_close_location":0.55},
    }
    x=prepared_observability(
        payload,
        prepared_reference=None,
        final_plan=None,
        kind="NONE",
        confirmed=False,
    )
    assert x["blueprint_block_reason"]=="FORECAST_TARGET_GEOMETRY_INVALID"
    assert x["forecast_selector_grade"]=="A"
    assert x["zone_low"]==4350.0
    assert x["zone_high"]==4359.0
    assert x["zone_distance_atr"]==0.4
    assert x["h4_directional_close_location"]==0.55


def test_afic_prepared_observability_explains_confirmed_live_geometry_failure():
    payload={
        "state":"CONFIRMED_NO_TARGET_GEOMETRY",
        "map_at":"2026-09-22T00:00:00+00:00",
        "continuation_direction":"LONG",
        "zone":{"low":4320.0,"high":4325.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.5,"h4_directional_close_location":0.60},
    }
    prepared={"entry":4325.0,"stop":4319.0}
    x=prepared_observability(
        payload,
        prepared_reference=prepared,
        final_plan=prepared,
        kind="NONE",
        confirmed=True,
    )
    assert x["blueprint_block_reason"]=="CONFIRMED_LIVE_TARGET_GEOMETRY_INVALID"
    assert x["forecast_selector_grade"]=="A"
    assert x["prepared_reference_entry"]==4325.0


def test_afic_forecast_state_transition_identity_and_key_are_durable():
    assert STATE_CODE=="XAU_AFIC_PATH_STATE_V1"
    assert STATE_EVENT_TYPE=="DEMO_XAU_AFIC_FORECAST_STATE"
    base={
        "map_at":"2026-09-22T00:00:00+00:00",
        "state":"ZONE_TOUCHED_WAIT_CONFIRM",
        "continuation_direction":"LONG",
        "first_touch_at":"2026-09-22T00:30:00+00:00",
        "zone":{"origin_at":"2026-09-21T11:00:00+00:00"},
    }
    touched=forecast_state_key(base)
    invalidated=forecast_state_key({
        **base,
        "state":"INVALIDATED_AFTER_TOUCH_REMAP_DUE",
        "invalidated_at":"2026-09-22T02:00:00+00:00",
    })
    assert touched!=invalidated
    assert "ZONE_TOUCHED_WAIT_CONFIRM" in touched
    assert "INVALIDATED_AFTER_TOUCH_REMAP_DUE" in invalidated
    assert "2026-09-22T02:00:00+00:00" in invalidated


def test_afic_grade_a_confirmed_is_only_auto_ready_state():
    state,guards=signal_state_and_guards(
        execution_enabled=True,confirmed=True,grade="A"
    )
    assert state=="EXECUTION_READY"
    assert guards==[]

    state_b,guards_b=signal_state_and_guards(
        execution_enabled=True,confirmed=True,grade="B"
    )
    assert state_b=="ARMED"
    assert "AFIC_SELECTOR_GRADE_A_REQUIRED" in guards_b

    state_wait,guards_wait=signal_state_and_guards(
        execution_enabled=True,confirmed=False,grade="A"
    )
    assert state_wait=="ARMED"
    assert "AFIC_M15_CONFIRMATION_REQUIRED" in guards_wait


def test_afic_zone_proximity_activates_one_minute_near_zone():
    zone={"low":4342.0,"high":4356.0,"h1_atr":14.0}
    near=zone_proximity(price=4363.0,zone=zone)
    assert near["proximity_state"]=="NEAR_ZONE"
    assert near["distance_atr"]==0.5
    assert near["recommended_scan_seconds"]==60

    inside=zone_proximity(price=4350.0,zone=zone)
    assert inside["inside_zone"] is True
    assert inside["recommended_scan_seconds"]==60

    far=zone_proximity(price=4385.0,zone=zone)
    assert far["proximity_state"]=="FAR"
    assert far["recommended_scan_seconds"]==300

from fx_scanner.demo_xau_afic_prepared_plan_producer import (
    EXECUTION_STRATEGY_ID,MAX_H4_DIRECTIONAL_CLOSE_LOC,MAX_ZONE_DISTANCE_ATR,
    STRATEGY_ID,prepared_blueprint,selector_grade
)

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

from datetime import datetime,timezone

from fx_scanner.demo_xau_afic_prepared_plan_producer import (
    EXECUTION_STRATEGY_ID,MAX_H4_DIRECTIONAL_CLOSE_LOC,MAX_ZONE_DISTANCE_ATR,
    STATE_CODE,STATE_EVENT_TYPE,STRATEGY_ID,confirmation_latency_seconds,
    entry_drift_metrics,enrich_alternative_reversal_watches,forecast_state_key,prepared_blueprint,
    prepared_observability,selector_grade,signal_state_and_guards,zone_proximity,
    geometry_matches_current_forecast,_invalidate_superseded_afic_signals
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
        "first_touch_at":"2026-09-21T23:45:00+00:00",
        "map_first_touch_at":"2026-09-22T00:30:00+00:00",
        "touch_lifecycle":"TOUCHED_DURING_CURRENT_MAP",
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
    assert "2026-09-22T00:30:00+00:00" in touched
    assert "TOUCHED_DURING_CURRENT_MAP" in touched
    assert "2026-09-22T02:00:00+00:00" in invalidated


def test_alternative_watch_lifecycle_transition_changes_forecast_state_key():
    base={
        "map_at":"2026-09-22T12:00:00+00:00",
        "state":"NO_MAP_ZONE",
        "continuation_direction":"LONG",
        "zone_diagnostics":{"alternative_reversal_watch_zones":[{
            "zone_id":"d53de19dc6617446d9c4ce42",
            "zone_lifecycle":"TOUCHED_BEFORE_CURRENT_MAP",
            "first_touch_at":"2026-09-22T08:45:00+00:00",
            "map_first_touch_at":None,
            "invalidated_at":None,
        }]},
    }
    touched_during_map={
        **base,
        "zone_diagnostics":{"alternative_reversal_watch_zones":[{
            **base["zone_diagnostics"]["alternative_reversal_watch_zones"][0],
            "zone_lifecycle":"TOUCHED_DURING_CURRENT_MAP",
            "map_first_touch_at":"2026-09-22T12:15:00+00:00",
        }]},
    }
    invalidated={
        **touched_during_map,
        "zone_diagnostics":{"alternative_reversal_watch_zones":[{
            **touched_during_map["zone_diagnostics"]["alternative_reversal_watch_zones"][0],
            "zone_lifecycle":"INVALIDATED_DURING_CURRENT_MAP",
            "invalidated_at":"2026-09-22T13:00:00+00:00",
        }]},
    }
    assert forecast_state_key(base)!=forecast_state_key(touched_during_map)
    assert forecast_state_key(touched_during_map)!=forecast_state_key(invalidated)


def test_live_quote_churn_does_not_change_alternative_lifecycle_state_key():
    base={
        "map_at":"2026-09-22T12:00:00+00:00",
        "state":"NO_MAP_ZONE",
        "zone_diagnostics":{"alternative_reversal_watch_zones":[{
            "zone_id":"ZONE_A",
            "zone_lifecycle":"UNTOUCHED",
            "first_touch_at":None,
            "map_first_touch_at":None,
            "invalidated_at":None,
        }]},
    }
    quote_update={
        **base,
        "zone_diagnostics":{"alternative_reversal_watch_zones":[{
            **base["zone_diagnostics"]["alternative_reversal_watch_zones"][0],
            "live_price":4340.0,
            "live_touch_at":"2026-09-22T12:11:00+00:00",
        }]},
    }
    assert forecast_state_key(base)==forecast_state_key(quote_update)


def test_afic_grade_a_and_b_confirmed_are_demo_auto_ready():
    for grade in ("A","B"):
        state,guards=signal_state_and_guards(
            execution_enabled=True,confirmed=True,grade=grade
        )
        assert state=="EXECUTION_READY"
        assert guards==[]

    state_c,guards_c=signal_state_and_guards(
        execution_enabled=True,confirmed=True,grade="C"
    )
    assert state_c=="ARMED"
    assert "AFIC_SELECTOR_GRADE_AB_REQUIRED" in guards_c

    state_wait,guards_wait=signal_state_and_guards(
        execution_enabled=True,confirmed=False,grade="B"
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


def test_afic_live_quote_marks_alternative_short_watch_touched_without_authority():
    payload={
        "state":"NO_MAP_ZONE",
        "zone_diagnostics":{
            "active_alternative_watch_count":1,
            "alternative_reversal_watch_zones":[{
                "direction":"SHORT",
                "role":"UPSIDE_DESTINATION_SHORT_REVERSAL_WATCH",
                "low":4335.07,
                "high":4342.98,
                "status":"ACTIVE_WATCH",
                "first_touch_at":None,
                "auto_execution_authority":False,
            }],
        },
    }
    now=datetime(2026,9,22,12,11,tzinfo=UTC)
    x=enrich_alternative_reversal_watches(payload,live_price=4342.0,observed_at=now)
    watch=x["zone_diagnostics"]["alternative_reversal_watch_zones"][0]
    assert watch["status"]=="LIVE_TOUCH_PENDING_M15_CLOSE"
    assert watch["live_inside_zone"] is True
    assert watch["distance_from_live_price_points"]==0.0
    assert watch["live_touch_at"]==now.isoformat()
    assert watch["live_touch_pending_m15_close"] is True
    assert watch["first_touch_at"] is None
    assert watch.get("map_first_touch_at") is None
    assert watch["auto_execution_authority"] is False
    assert x["zone_diagnostics"]["live_touched_alternative_watch_count"]==1


def test_afic_live_quote_updates_watch_distance_without_fabricating_touch():
    payload={
        "zone_diagnostics":{
            "active_alternative_watch_count":1,
            "alternative_reversal_watch_zones":[{
                "direction":"SHORT",
                "low":4342.0,
                "high":4355.0,
                "status":"ACTIVE_WATCH",
                "first_touch_at":None,
                "auto_execution_authority":False,
            }],
        },
    }
    x=enrich_alternative_reversal_watches(
        payload,live_price=4332.0,observed_at=datetime(2026,9,22,12,5,tzinfo=UTC)
    )
    watch=x["zone_diagnostics"]["alternative_reversal_watch_zones"][0]
    assert watch["status"]=="ACTIVE_WATCH"
    assert watch["live_touch"] is False
    assert watch["distance_from_live_price_points"]==10.0
    assert watch["first_touch_at"] is None


def test_afic_execution_geometry_must_match_current_confirmed_map():
    geometry={
        "map_at":"2026-09-22T04:00:00+00:00",
        "confirm_at":"2026-09-22T04:45:00+00:00",
    }
    current={
        "state":"CONFIRMED_SHADOW",
        "map_at":"2026-09-22T04:00:00+00:00",
        "confirm_at":"2026-09-22T04:45:00+00:00",
    }
    assert geometry_matches_current_forecast(geometry,current) is True
    assert geometry_matches_current_forecast(
        geometry,{**current,"state":"INVALIDATED_AFTER_TOUCH_REMAP_DUE"}
    ) is False
    assert geometry_matches_current_forecast(
        geometry,{**current,"map_at":"2026-09-22T08:00:00+00:00"}
    ) is False


class _Resp:
    def __init__(self,data):
        self.data=data


class _Query:
    def __init__(self,client,table):
        self.client=client
        self.table=table
        self.filters=[]
        self.patch=None
    def select(self,*args,**kwargs):
        return self
    def update(self,patch):
        self.patch=dict(patch)
        return self
    def eq(self,key,value):
        self.filters.append((key,value))
        return self
    def order(self,*args,**kwargs):
        return self
    def limit(self,*args,**kwargs):
        return self
    def execute(self):
        rows=list(self.client.rows.get(self.table,[]))
        for key,value in self.filters:
            rows=[r for r in rows if r.get(key)==value]
        if self.patch is not None:
            for row in rows:
                row.update(self.patch)
            return _Resp(rows)
        return _Resp(rows)


class _Client:
    def __init__(self,rows):
        self.rows=rows
    def table(self,name):
        return _Query(self,name)


class _Store:
    def __init__(self,rows):
        self.client=_Client(rows)


def test_superseded_afic_armed_signal_is_invalidated_on_new_h4_map():
    signal={"id":"old-signal","state":"ARMED","active_guards":[]}
    store=_Store({
        "broker_order_events":[{
            "signal_key":"old-signal",
            "event_type":"DEMO_XAU_AFIC_PREPARED_PLAN",
            "code":"XAU_AFIC_PATH_PREPARED_V1",
            "payload":{"forecast":{"map_at":"2026-09-22T08:00:00+00:00"}},
        }],
        "signals":[signal],
    })
    n=_invalidate_superseded_afic_signals(
        store,payload={"map_at":"2026-09-22T12:00:00+00:00"}
    )
    assert n==1
    assert signal["state"]=="INVALIDATED"
    assert signal["active_guards"]==["AFIC_MAP_SUPERSEDED"]


def test_same_afic_map_remains_armed():
    signal={"id":"same-signal","state":"ARMED","active_guards":[]}
    store=_Store({
        "broker_order_events":[{
            "signal_key":"same-signal",
            "event_type":"DEMO_XAU_AFIC_PREPARED_PLAN",
            "code":"XAU_AFIC_PATH_PREPARED_V1",
            "payload":{"forecast":{"map_at":"2026-09-22T12:00:00+00:00"}},
        }],
        "signals":[signal],
    })
    n=_invalidate_superseded_afic_signals(
        store,payload={"map_at":"2026-09-22T12:00:00+00:00"}
    )
    assert n==0
    assert signal["state"]=="ARMED"


def test_afic_v229_structural_targets_replace_round_number_as_primary_tp_source():
    payload={
        "continuation_direction":"LONG",
        "zone":{"low":4250.0,"high":4258.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.4,"h4_directional_close_location":0.55},
        "supply_demand_context":{
            "structural_target_context":{
                "m15_opposing_zones":[{
                    "zone_id":"m15-s","timeframe":"M15","direction":"SHORT",
                    "low":4274.0,"high":4278.0,"status":"ACTIVE",
                    "lifecycle":{"active":True},
                }],
                "htf_destination_stack":[
                    {"zone_id":"h1-s","timeframe":"H1","direction":"SHORT",
                     "low":4290.0,"high":4300.0,"status":"ACTIVE"},
                    {"zone_id":"h4-s","timeframe":"H4","direction":"SHORT",
                     "low":4320.0,"high":4340.0,"status":"ACTIVE"},
                ],
            }
        },
    }
    plan=prepared_blueprint(payload)
    assert plan is not None
    assert plan["target_model"]=="STRUCTURAL_SUPPLY_DEMAND_PRIMARY"
    assert plan["tp_ladder"]==[4273.6,4289.0,4319.0]
    assert plan["tp1"]==4273.6
    assert plan["tp2"]==4319.0
    assert [x["timeframe"] for x in plan["structural_target_ladder"]]==["M15","H1","H4"]
    assert plan["legacy_round_fallback"]["tp_ladder"]


def test_afic_v229_falls_back_only_when_no_structural_target_passes_rr():
    payload={
        "continuation_direction":"LONG",
        "zone":{"low":100.0,"high":105.0,"h1_atr":10.0},
        "h4_features":{"zone_distance_atr":0.4,"h4_directional_close_location":0.55},
        "supply_demand_context":{
            "structural_target_context":{
                "m15_opposing_zones":[{
                    "zone_id":"too-near","timeframe":"M15","direction":"SHORT",
                    "low":108.0,"high":110.0,"status":"ACTIVE",
                    "lifecycle":{"active":True},
                }],
                "htf_destination_stack":[],
            }
        },
    }
    plan=prepared_blueprint(payload)
    assert plan is not None
    assert plan["target_model"]=="LEGACY_RR_ROUND_FALLBACK_NO_ELIGIBLE_STRUCTURAL_TARGET"
    assert plan["structural_target_ladder"][0]["rr_eligible"] is False
    assert plan["rr2"]>=1.5

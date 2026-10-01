from fx_scanner.xau_simple_decision_v336 import build_simple_decision


def _path(*, price_inside=True):
    return {
        "active_direction": "SHORT",
        "next_decision_zone": {
            "low": 4151.0,
            "high": 4162.0,
            "direction": "LONG",
            "timeframe": "H1",
        },
        "decision_zone_relation": "INSIDE" if price_inside else "ABOVE",
        "key_levels": {
            "rejection_rule": "M5 reclaim above proximal",
            "acceptance_rule": "M15 accepts below distal",
            "rejection_reclaim_key": 4161.0,
            "break_acceptance_key": 4151.0,
        },
        "rejection_branch": {"direction": "LONG"},
        "acceptance_branch": {"direction": "SHORT"},
    }


def _canonical():
    return {
        "direction": "LONG",
        "entry_reference": 4158.0,
        "entry_low": 4156.0,
        "entry_high": 4159.0,
        "sl": 4148.0,
        "tp1": 4175.0,
        "tp2": 4185.0,
    }


def test_short_travel_into_demand_is_not_presented_as_direction_conflict():
    result = build_simple_decision(
        price_now=4157.0,
        path_engine=_path(price_inside=True),
        micro_evaluation={"primary": {"direction": "LONG", "phase": "WAIT_ANCHOR_A"}},
        canonical_decision=_canonical(),
        reversal_stage={"stage": "REVERSAL_WATCH", "demo_entry_allowed": False},
        admission_label="WAIT",
        backend_stale=False,
        position_mode=False,
        effective_entry_authorized=False,
    )
    assert result["action"] == "WAIT REVERSAL LONG"
    assert result["travel_direction"] == "SHORT"
    assert result["reversal_direction"] == "LONG"
    assert result["travel_vs_reversal"] == "SEQUENTIAL_NOT_CONFLICT"
    assert result["geometry"]["entry"] is None


def test_entry_geometry_is_exposed_only_when_effectively_authorized():
    result = build_simple_decision(
        price_now=4158.0,
        path_engine=_path(price_inside=True),
        micro_evaluation={"primary": {"direction": "LONG", "phase": "CONFIRMED"}},
        canonical_decision=_canonical(),
        reversal_stage={"stage": "DEMO_ENTRY_ALLOWED", "demo_entry_allowed": True},
        admission_label="BROKER ELIGIBLE",
        backend_stale=False,
        position_mode=False,
        effective_entry_authorized=True,
    )
    assert result["action"] == "LONG — ENTRY READY"
    assert result["entry_authorized"] is True
    assert result["geometry"]["entry"] == 4158.0
    assert result["geometry"]["sl"] == 4148.0
    assert result["geometry"]["tp1"] == 4175.0


def test_stale_data_is_always_no_order():
    result = build_simple_decision(
        price_now=4158.0,
        path_engine=_path(price_inside=True),
        micro_evaluation={"primary": {"direction": "LONG", "phase": "CONFIRMED"}},
        canonical_decision=_canonical(),
        reversal_stage={"stage": "DEMO_ENTRY_ALLOWED", "demo_entry_allowed": True},
        admission_label="BROKER ELIGIBLE",
        backend_stale=True,
        position_mode=False,
        effective_entry_authorized=True,
    )
    assert result["action"] == "DATA STALE — NO ORDER"
    assert result["entry_authorized"] is False
    assert result["geometry"]["entry"] is None


def test_outside_decision_zone_shows_travel_story_instead_of_reversal_entry():
    result = build_simple_decision(
        price_now=4170.0,
        path_engine=_path(price_inside=False),
        micro_evaluation={},
        canonical_decision=_canonical(),
        reversal_stage={"stage": "PREPARE", "demo_entry_allowed": False},
        admission_label="WAIT",
        backend_stale=False,
        position_mode=False,
        effective_entry_authorized=False,
    )
    assert result["action"] == "TRAVEL SHORT → DEMAND"
    assert result["action_class"] == "TRAVEL"

from datetime import UTC, datetime, timedelta

import fx_scanner.demo_xau_afic_supply_demand_context as ctx
from fx_scanner.demo_xau_afic_prepared_plan_producer import (
    selector_grade,
    signal_state_and_guards,
)


class DummyStore:
    pass


def _atlas():
    return {
        "state": "ATLAS_AVAILABLE",
        "last_closed_m15_price": 4303.82,
        "session_context": "US_MACRO_WINDOW_1930_2029_WIB",
        "nearest_demand": {
            "zone_id": "demand-1",
            "timeframe": "H1",
            "zone_class": "STRUCTURAL",
            "pattern": "STRUCTURAL_DEMAND",
            "direction": "LONG",
            "low": 4273.96,
            "high": 4300.95,
            "atr_points": 22.64,
            "distance_atr": 0.1267,
            "status": "APPROACHING_PREPARE_ONLY",
            "lifecycle": {"freshness": "SECOND_TEST", "touch_count": 2},
            "approach": {"state": "CONTROLLED_APPROACH"},
            "nested_in": ["H4:a", "H4:b", "H4:c"],
            "htf_nesting_count": 3,
        },
        "nearest_supply": {
            "zone_id": "supply-1",
            "timeframe": "H1",
            "zone_class": "IMBALANCE",
            "pattern": "RBD",
            "direction": "SHORT",
            "low": 4342.5,
            "high": 4347.3,
            "atr_points": 14.8,
            "distance_atr": 2.6,
            "status": "ACTIVE_WATCH_PREPARE_ONLY",
            "lifecycle": {"freshness": "FRESH", "touch_count": 0},
            "approach": {"state": "FLAT_OR_AWAY"},
            "nested_in": ["H4:x", "D1:y"],
            "htf_nesting_count": 2,
        },
    }


def test_no_map_zone_becomes_prepare_context_only(monkeypatch):
    now = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, _atlas()))
    payload = {
        "state": "NO_MAP_ZONE",
        "map_price": 4319.56,
        "continuation_direction": "SHORT",
        "first_leg_direction": "LONG",
    }
    out = ctx.attach_supply_demand_context(DummyStore(), payload, observed_at=now)
    sd = out["supply_demand_context"]
    assert sd["state"] == "NO_CANONICAL_ZONE_SUPPLY_DEMAND_PREPARE_ONLY"
    assert sd["prepare_only_fallback"] is True
    assert sd["required_for_execution"] is False
    assert sd["execution_influence"] is False
    assert sd["execution_authority"] is False
    assert sd["same_direction_zone"]["zone_id"] == "supply-1"
    assert sd["opposite_reversal_zone"]["zone_id"] == "demand-1"
    assert sd["opposite_zone_near_price"] is True
    assert sd["opposite_zone_distance_atr"] < 0.2


def test_canonical_overlap_is_confluence_not_authority(monkeypatch):
    now = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    atlas = _atlas()
    atlas["nearest_supply"] = {
        **atlas["nearest_supply"],
        "low": 4341.0,
        "high": 4348.0,
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    payload = {
        "state": "APPROACHING_ZONE",
        "map_price": 4319.56,
        "continuation_direction": "SHORT",
        "first_leg_direction": "LONG",
        "zone": {
            "zone_id": "canonical-short",
            "low": 4342.0,
            "high": 4347.0,
            "h1_atr": 15.0,
        },
    }
    out = ctx.attach_supply_demand_context(DummyStore(), payload, observed_at=now)
    sd = out["supply_demand_context"]
    assert sd["state"] == "CANONICAL_OVERLAPS_SUPPLY_DEMAND"
    assert sd["same_direction_overlap_ratio"] > 0
    assert sd["same_direction_confluence"] is True
    assert sd["execution_authority"] is False


def test_stale_atlas_has_no_policy_effect(monkeypatch):
    now = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    old = now - timedelta(minutes=30)
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (old, _atlas()))
    out = ctx.attach_supply_demand_context(
        DummyStore(),
        {
            "state": "NO_MAP_ZONE",
            "continuation_direction": "LONG",
            "first_leg_direction": "SHORT",
        },
        observed_at=now,
    )
    sd = out["supply_demand_context"]
    assert sd["state"] == "ATLAS_STALE_NO_POLICY_EFFECT"
    assert sd["atlas_stale"] is True
    assert sd["execution_influence"] is False


def test_supply_demand_context_does_not_change_grade_or_execution_gate():
    features = {
        "zone_distance_atr": 0.40,
        "h4_directional_close_location": 0.50,
    }
    before = selector_grade(features)
    payload_with_context = {
        "h4_features": features,
        "supply_demand_context": {
            "same_direction_confluence": True,
            "execution_authority": False,
        },
    }
    after = selector_grade(payload_with_context["h4_features"])
    assert before == after == "A"

    state, guards = signal_state_and_guards(
        execution_enabled=True,
        confirmed=False,
        grade=after,
    )
    assert state == "ARMED"
    assert "AFIC_M15_CONFIRMATION_REQUIRED" in guards

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


def test_afic_first_leg_uses_matching_supply_demand_path(monkeypatch):
    now = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    atlas = _atlas()
    atlas["path_map"] = {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "demand_to_supply": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {"zone_id": "demand-1", "low": 4273.96, "high": 4300.95},
            "primary_opposing_zone": {"zone_id": "supply-near", "low": 4342.51, "high": 4347.27},
            "internal_targets": [{"source": "H1_SWING_HIGH", "price": 4331.0}],
            "execution_authority": False,
        },
        "supply_to_demand": {
            "state": "SOURCE_ZONE_WATCH",
            "reaction_direction": "SHORT",
            "source_zone": {"zone_id": "supply-near", "low": 4342.51, "high": 4347.27},
            "primary_opposing_zone": {"zone_id": "demand-1", "low": 4273.96, "high": 4300.95},
            "internal_targets": [],
            "execution_authority": False,
        },
        "active_path": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {"zone_id": "demand-1", "low": 4273.96, "high": 4300.95},
            "primary_opposing_zone": {"zone_id": "supply-near", "low": 4342.51, "high": 4347.27},
            "internal_targets": [{"source": "H1_SWING_HIGH", "price": 4331.0}],
            "execution_authority": False,
        },
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    out = ctx.attach_supply_demand_context(
        DummyStore(),
        {
            "state": "NO_MAP_ZONE",
            "continuation_direction": "SHORT",
            "first_leg_direction": "LONG",
        },
        observed_at=now,
    )
    sd = out["supply_demand_context"]
    assert sd["first_leg_path"]["reaction_direction"] == "LONG"
    assert sd["first_leg_path"]["source_zone"]["zone_id"] == "demand-1"
    assert sd["first_leg_path"]["primary_opposing_zone"]["zone_id"] == "supply-near"
    assert sd["first_leg_path"]["execution_authority"] is False


def test_overlapping_opposite_h1_paths_are_flagged_as_compression_conflict(monkeypatch):
    now = datetime(2026, 9, 23, 21, 55, tzinfo=UTC)
    atlas = _atlas()
    atlas["path_map"] = {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "demand_to_supply": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "primary_opposing_zone": {
                "zone_id": "supply-next",
                "timeframe": "H4",
                "low": 4294.71,
                "high": 4322.79,
            },
            "execution_authority": False,
        },
        "supply_to_demand": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "SHORT",
            "source_zone": {
                "zone_id": "supply-overlap",
                "timeframe": "H1",
                "low": 4277.82,
                "high": 4298.55,
            },
            "primary_opposing_zone": {
                "zone_id": "demand-next",
                "timeframe": "H4",
                "low": 4257.53,
                "high": 4276.30,
            },
            "execution_authority": False,
        },
        "active_path": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "primary_opposing_zone": {
                "zone_id": "supply-next",
                "timeframe": "H4",
                "low": 4294.71,
                "high": 4322.79,
            },
            "execution_authority": False,
        },
        "micro_refinement": {
            "state": "M5_RECLAIM_WAIT_MSS",
            "direction": "LONG",
            "execution_authority": False,
        },
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    out = ctx.attach_supply_demand_context(
        DummyStore(),
        {
            "state": "NO_MAP_ZONE",
            "continuation_direction": "SHORT",
            "first_leg_direction": "SHORT",
        },
        observed_at=now,
    )
    sd = out["supply_demand_context"]
    assert sd["path_direction_conflict"] is True
    assert sd["path_overlap_ratio"] > 0.60
    assert sd["micro_resolution_required"] is True
    assert sd["path_conflict_state"] == (
        "OVERLAPPING_H1_SUPPLY_DEMAND_COMPRESSION_WAIT_MICRO_RESOLUTION"
    )
    assert sd["execution_authority"] is False


def test_v191_dom_supports_long_first_leg_without_execution_authority(monkeypatch):
    now = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)
    atlas = _atlas()
    atlas["path_map"] = {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "demand_to_supply": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-1",
                "timeframe": "H1",
                "low": 4273.96,
                "high": 4300.95,
            },
            "primary_opposing_zone": {
                "zone_id": "supply-near",
                "timeframe": "H1",
                "low": 4342.51,
                "high": 4347.27,
            },
            "execution_authority": False,
        },
        "supply_to_demand": {},
        "active_path": {},
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    monkeypatch.setattr(
        ctx,
        "latest_dom",
        lambda store: (
            now,
            {
                "state": "BID_DOMINANT",
                "dom_pressure_score": 71.5,
                "last_imbalance": 0.31,
                "top5_bid_units": 25000.0,
                "top5_ask_units": 13000.0,
                "bid_wall": {"dominant_wall_price": 4288.5, "wall_persistence": 0.8},
                "ask_wall": {"dominant_wall_price": 4294.5, "wall_persistence": 0.3},
            },
        ),
    )
    out = ctx.attach_supply_demand_context(
        DummyStore(),
        {
            "state": "NO_MAP_ZONE",
            "continuation_direction": "SHORT",
            "first_leg_direction": "LONG",
        },
        observed_at=now,
    )
    dom = out["supply_demand_context"]["dom_context"]
    assert dom["state"] == "BID_DOMINANT"
    assert dom["alignment_with_first_leg"] == "SUPPORTS_FIRST_LEG"
    assert dom["execution_authority"] is False
    assert out["supply_demand_context"]["execution_authority"] is False


def test_v191_dom_and_v189_can_align_but_remain_shadow(monkeypatch):
    now = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)
    atlas = _atlas()
    atlas["path_map"] = {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "demand_to_supply": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "execution_authority": False,
        },
        "supply_to_demand": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "SHORT",
            "source_zone": {
                "zone_id": "supply-overlap",
                "timeframe": "H1",
                "low": 4277.82,
                "high": 4298.55,
            },
            "execution_authority": False,
        },
        "active_path": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "execution_authority": False,
        },
        "micro_refinement": {
            "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
            "direction": "LONG",
            "execution_authority": False,
        },
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    monkeypatch.setattr(
        ctx,
        "latest_dom",
        lambda store: (
            now,
            {
                "state": "BID_DOMINANT",
                "dom_pressure_score": 70.0,
                "last_imbalance": 0.25,
            },
        ),
    )
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
    assert sd["path_direction_conflict"] is True
    assert sd["conflict_resolution_evidence"] == "M5_AND_DOM_ALIGNED_SHADOW"
    assert sd["execution_authority"] is False


def test_v192_event_risk_is_context_only(monkeypatch):
    now = datetime(2026, 9, 24, 12, 10, tzinfo=UTC)
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, _atlas()))
    monkeypatch.setattr(ctx, "latest_dom", lambda store: (now, {}))
    monkeypatch.setattr(
        ctx,
        "latest_event_risk",
        lambda store: (
            now,
            {
                "risk": {
                    "state": "PRE_EVENT",
                    "action": "PREPARE_ONLY_AVOID_NEW_CHASE",
                    "minutes_to_focal": 20.0,
                    "focal_event": {
                        "title": "Initial Jobless Claims",
                        "scheduled_at": "2026-09-24T12:30:00+00:00",
                        "scheduled_at_wib": "2026-09-24T19:30:00+07:00",
                        "source_tier": "OFFICIAL_DOL_CADENCE_MATCHED",
                        "source": "FOREX_FACTORY_WEEKLY",
                    },
                    "upcoming_events": [],
                },
                "official_or_cadence_verified_count": 1,
                "discovery_unverified_count": 0,
                "source_status": {"FOREX_FACTORY_WEEKLY": "OK:1"},
            },
        ),
    )
    out = ctx.attach_supply_demand_context(
        DummyStore(),
        {
            "state": "NO_MAP_ZONE",
            "continuation_direction": "SHORT",
            "first_leg_direction": "LONG",
        },
        observed_at=now,
    )
    event = out["supply_demand_context"]["event_risk_context"]
    assert event["state"] == "PRE_EVENT"
    assert event["action"] == "PREPARE_ONLY_AVOID_NEW_CHASE"
    assert event["execution_authority"] is False
    assert out["supply_demand_context"]["execution_authority"] is False


def test_v192_pre_event_keeps_m5_dom_alignment_shadow_only(monkeypatch):
    now = datetime(2026, 9, 24, 12, 10, tzinfo=UTC)
    atlas = _atlas()
    atlas["path_map"] = {
        "contract": "XAU_SUPPLY_DEMAND_PATH_ENGINE_V186",
        "demand_to_supply": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "execution_authority": False,
        },
        "supply_to_demand": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "SHORT",
            "source_zone": {
                "zone_id": "supply-overlap",
                "timeframe": "H1",
                "low": 4277.82,
                "high": 4298.55,
            },
            "execution_authority": False,
        },
        "active_path": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": {
                "zone_id": "demand-overlap",
                "timeframe": "H1",
                "low": 4266.43,
                "high": 4292.31,
            },
            "execution_authority": False,
        },
        "micro_refinement": {
            "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
            "direction": "LONG",
            "execution_authority": False,
        },
    }
    monkeypatch.setattr(ctx, "latest_atlas", lambda store: (now, atlas))
    monkeypatch.setattr(
        ctx,
        "latest_dom",
        lambda store: (
            now,
            {
                "state": "BID_DOMINANT",
                "dom_pressure_score": 72.0,
                "last_imbalance": 0.28,
            },
        ),
    )
    monkeypatch.setattr(
        ctx,
        "latest_event_risk",
        lambda store: (
            now,
            {
                "risk": {
                    "state": "PRE_EVENT",
                    "action": "PREPARE_ONLY_AVOID_NEW_CHASE",
                    "minutes_to_focal": 15.0,
                    "focal_event": {
                        "title": "CPI",
                        "scheduled_at": "2026-09-24T12:25:00+00:00",
                    },
                    "upcoming_events": [],
                }
            },
        ),
    )
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
    assert sd["path_direction_conflict"] is True
    assert sd["conflict_resolution_evidence"] == "M5_DOM_ALIGNED_BUT_EVENT_RISK_WAIT"
    assert sd["event_risk_context"]["state"] == "PRE_EVENT"
    assert sd["execution_authority"] is False

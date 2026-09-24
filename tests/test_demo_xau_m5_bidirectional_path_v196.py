from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_m5_bidirectional_path_v196 import (
    CONTRACT,
    evaluate_bidirectional_m5_path,
)
from fx_scanner.models import Bar


def _bar(ts, o, h, l, c):
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=ts,
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        tick_count=100,
        spread_avg=0.0,
        spread_max=0.0,
    )


def _long_then_short_path():
    demand = {
        "zone_id": "demand-h1",
        "timeframe": "H1",
        "direction": "LONG",
        "low": 100.0,
        "high": 110.0,
        "proximal": 105.0,
        "distal": 100.0,
        "available_at": "2026-09-22T00:00:00+00:00",
    }
    supply = {
        "zone_id": "supply-h1",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 120.0,
        "high": 130.0,
        "proximal": 125.0,
        "distal": 130.0,
        "available_at": "2026-09-22T00:00:00+00:00",
    }
    return {
        "active_path": {
            "state": "SOURCE_ZONE_ENTERED_WAIT_REACTION_CONFIRMATION",
            "reaction_direction": "LONG",
            "source_zone": demand,
            "reaction_target": {"price": 119.0},
            "terminal_target_zone": supply,
            "primary_opposing_zone": supply,
            "target_ladder": [{"role": "REACTION_TARGET", "price": 119.0}],
        },
        "demand_to_supply": {
            "reaction_direction": "LONG",
            "source_zone": demand,
            "reaction_target": {"price": 119.0},
            "terminal_target_zone": supply,
            "primary_opposing_zone": supply,
        },
        "supply_to_demand": {
            "state": "SOURCE_ZONE_WATCH",
            "reaction_direction": "SHORT",
            "source_zone": supply,
            "reaction_target": {"price": 111.0},
            "terminal_target_zone": demand,
            "primary_opposing_zone": demand,
            "target_ladder": [{"role": "REACTION_TARGET", "price": 111.0}],
        },
    }


def test_v196_contract_is_shadow_only_without_path():
    out = evaluate_bidirectional_m5_path(
        (),
        path_map={},
        as_of=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert CONTRACT == "XAU_BIDIRECTIONAL_M5_PATH_V196"
    assert out["state"] == "NO_ACTIVE_PATH"
    assert out["execution_authority"] is False
    assert out["promotion_authority"] is False


def test_v196_premaps_reverse_leg_and_targets_without_inventing_pocket():
    t0 = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    bars = [
        _bar(t0 + timedelta(minutes=5 * i), 111.0, 113.0, 110.0, 112.0)
        for i in range(60)
    ]
    out = evaluate_bidirectional_m5_path(
        tuple(bars),
        path_map=_long_then_short_path(),
        as_of=t0 + timedelta(minutes=5 * 61),
    )
    assert out["current_leg"]["direction"] == "LONG"
    assert out["current_leg"]["reaction_target"]["price"] == 119.0
    assert out["next_leg"]["direction"] == "SHORT"
    assert out["next_leg"]["source_zone"]["zone_id"] == "supply-h1"
    assert out["next_leg"]["reaction_target"]["price"] == 111.0
    assert out["next_leg"]["parent_matches_current_terminal"] is True
    assert out["next_leg"]["pocket_state"] == "NO_M5_POCKET_YET"
    assert out["execution_influence"] is False


def test_v196_exposes_current_candidate_direction():
    t0 = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    bars = []
    for i in range(40):
        ts = t0 + timedelta(minutes=5 * i)
        if i == 20:
            bars.append(_bar(ts, 107.0, 111.0, 106.0, 108.0))
        elif i == 25:
            bars.append(_bar(ts, 108.0, 108.5, 101.5, 103.0))
        elif i >= 26:
            bars.append(_bar(ts, 103.0, 109.5, 102.5, 106.0))
        else:
            bars.append(_bar(ts, 106.0, 109.0, 105.0, 107.0))

    out = evaluate_bidirectional_m5_path(
        tuple(bars),
        path_map=_long_then_short_path(),
        as_of=t0 + timedelta(minutes=5 * 41),
    )
    assert out["current_leg"]["direction"] == "LONG"
    assert out["current_leg"]["pocket_state"] == "CANDIDATE_M5_POCKET"
    assert out["current_leg"]["m5_pocket"]
    assert out["current_leg"]["micro_refinement"]["state"] == "M5_RECLAIM_WAIT_MSS"


def test_v196_suppresses_invalidated_candidate_pocket():
    from fx_scanner.demo_xau_m5_bidirectional_path_v196 import _leg_payload

    path = {
        "state": "SOURCE_ZONE_APPROACHING",
        "source_zone": {
            "zone_id": "supply-x",
            "timeframe": "H1",
            "direction": "SHORT",
            "low": 120.0,
            "high": 130.0,
        },
        "reaction_target": {"price": 110.0},
        "terminal_target_zone": {"low": 100.0, "high": 105.0},
    }
    micro = {
        "state": "SOURCE_INVALIDATED_NO_REFINEMENT",
        "direction": "SHORT",
        "candidate_entry_pocket": {"low": 124.0, "high": 127.0},
        "refined_entry_pocket": None,
    }

    out = _leg_payload(direction="SHORT", path=path, micro=micro)

    assert out["pocket_state"] == "INVALIDATED_M5_POCKET"
    assert out["m5_pocket"] == {}
    assert out["historical_candidate_pocket"] == {"low": 124.0, "high": 127.0}
    assert out["reaction_target"]["price"] == 110.0


def test_v196_next_leg_uses_h1_precision_inside_current_terminal_not_global_nearest():
    t0 = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)
    bars = [
        _bar(t0 + timedelta(minutes=5 * i), 111.0, 113.0, 110.0, 112.0)
        for i in range(60)
    ]
    path_map = _long_then_short_path()
    h4_terminal = {
        "zone_id": "terminal-h4-supply",
        "timeframe": "H4",
        "direction": "SHORT",
        "low": 120.0,
        "high": 140.0,
        "lifecycle": {"active": True},
    }
    h1_precision = {
        "zone_id": "terminal-h1-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 123.0,
        "high": 129.0,
        "proximal": 123.0,
        "distal": 129.0,
        "available_at": "2026-09-22T00:00:00+00:00",
        "lifecycle": {"active": True},
    }
    path_map["active_path"]["terminal_target_zone"] = h4_terminal
    path_map["active_path"]["primary_opposing_zone"] = h4_terminal
    path_map["active_path"]["destination_stack"] = [h4_terminal, h1_precision]
    path_map["active_path"]["secondary_opposing_zones"] = [h1_precision]
    path_map["supply_to_demand"]["source_zone"] = {
        "zone_id": "old-nearest-supply",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 114.0,
        "high": 118.0,
        "proximal": 114.0,
        "distal": 118.0,
        "available_at": "2026-09-22T00:00:00+00:00",
    }

    out = evaluate_bidirectional_m5_path(
        tuple(bars),
        path_map=path_map,
        as_of=t0 + timedelta(minutes=5 * 61),
    )

    assert out["next_leg"]["source_zone"]["zone_id"] == "terminal-h1-supply"
    assert out["next_leg"]["source_role"] == "H1_PRECISION_INSIDE_CURRENT_TERMINAL"
    assert out["next_leg"]["parent_matches_current_terminal"] is True
    assert out["next_leg"]["pocket_state"] == "NO_M5_POCKET_YET"
    assert out["next_leg"]["micro_refinement"]["state"] == "WAIT_SOURCE_TOUCH"

from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_v196_shadow_evidence_v197 import (
    PocketSnapshot,
    _freeze_snapshot_geometry,
    _tracked_frozen_states,
    _preserve_first_enrollment,
    _snapshots_from_heartbeats,
    evaluate_pocket_outcome,
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


def _snapshot(direction="LONG"):
    return PocketSnapshot(
        episode_key="episode-1",
        observed_at=datetime(2026, 9, 24, 6, 0, tzinfo=UTC),
        leg_role="current_leg",
        direction=direction,
        pocket_state="CANDIDATE_M5_POCKET",
        pocket_low=100.0 if direction == "LONG" else 120.0,
        pocket_high=102.0 if direction == "LONG" else 122.0,
        pocket_origin_at="2026-09-24T05:55:00+00:00",
        source_role=None,
        source_zone={
            "zone_id": "source-1",
            "distal": 95.0 if direction == "LONG" else 127.0,
        },
        reaction_target=110.0 if direction == "LONG" else 112.0,
        terminal_zone=(
            {"low": 114.0, "high": 118.0}
            if direction == "LONG"
            else {"low": 104.0, "high": 108.0}
        ),
        projection_state="CURRENT_LEG_CANDIDATE_NEXT_LEG_PREMAPPED",
    )


def test_v197_requires_post_enrollment_touch_before_counting_target():
    snap = _snapshot("LONG")
    bars = (
        _bar(datetime(2026, 9, 24, 6, 5, tzinfo=UTC), 111, 115, 109, 114),
        _bar(datetime(2026, 9, 24, 6, 10, tzinfo=UTC), 104, 105, 103, 104),
    )
    out = evaluate_pocket_outcome(
        bars,
        snapshot=snap,
        as_of=datetime(2026, 9, 24, 6, 20, tzinfo=UTC),
    )
    assert out.first_touch_at is None
    assert out.reaction_hit is False
    assert out.terminal_hit is False
    assert out.status == "ENROLLED_WAIT_TOUCH"


def test_v197_records_long_shadow_target_without_order():
    snap = _snapshot("LONG")
    bars = (
        _bar(datetime(2026, 9, 24, 6, 5, tzinfo=UTC), 103, 103, 100.5, 102),
        _bar(datetime(2026, 9, 24, 6, 10, tzinfo=UTC), 102, 111, 101, 110),
    )
    out = evaluate_pocket_outcome(
        bars,
        snapshot=snap,
        as_of=datetime(2026, 9, 24, 6, 20, tzinfo=UTC),
    )
    assert out.first_touch_at == datetime(2026, 9, 24, 6, 5, tzinfo=UTC)
    assert out.reaction_hit is True
    assert out.terminal_hit is False
    assert out.status == "PROVEN_REACTION_TARGET"
    assert out.outcome_class == "PROVEN_REACTION_TARGET_NO_ORDER_REQUIRED"


def test_v197_records_short_terminal_zone_without_order():
    snap = _snapshot("SHORT")
    bars = (
        _bar(datetime(2026, 9, 24, 6, 5, tzinfo=UTC), 119, 121, 118, 120),
        _bar(datetime(2026, 9, 24, 6, 10, tzinfo=UTC), 120, 120, 107, 108),
    )
    out = evaluate_pocket_outcome(
        bars,
        snapshot=snap,
        as_of=datetime(2026, 9, 24, 6, 20, tzinfo=UTC),
    )
    assert out.reaction_hit is True
    assert out.terminal_hit is True
    assert out.status == "PROVEN_TERMINAL_ZONE"
    assert out.outcome_class == "PROVEN_TERMINAL_ZONE_NO_ORDER_REQUIRED"


def test_v197_invalidated_source_is_failure_not_proof():
    snap = _snapshot("LONG")
    bars = (
        _bar(datetime(2026, 9, 24, 6, 5, tzinfo=UTC), 101, 102, 99, 100),
        _bar(datetime(2026, 9, 24, 6, 10, tzinfo=UTC), 100, 101, 94, 94),
    )
    out = evaluate_pocket_outcome(
        bars,
        snapshot=snap,
        as_of=datetime(2026, 9, 24, 6, 20, tzinfo=UTC),
    )
    assert out.status == "INVALIDATED_AFTER_TOUCH"
    assert out.reaction_hit is False


def test_v197_ignores_pre_fix_reverse_leg_heartbeats():
    observed = "2026-09-24T06:30:00+00:00"
    projection = {
        "contract": "XAU_BIDIRECTIONAL_M5_PATH_V196",
        "state": "CURRENT_LEG_CANDIDATE_NEXT_LEG_PREMAPPED",
        "current_leg": {
            "direction": "LONG",
            "pocket_state": "CANDIDATE_M5_POCKET",
            "m5_pocket": {"low": 100, "high": 102, "origin_at": observed},
            "source_zone": {"zone_id": "d1", "distal": 95},
            "reaction_target": {"price": 110},
            "terminal_target_zone": {"low": 114, "high": 118},
            "micro_refinement": {"state": "M5_RECLAIM_WAIT_MSS"},
        },
        "next_leg": {
            "direction": "SHORT",
            "pocket_state": "CANDIDATE_M5_POCKET",
            "m5_pocket": {"low": 120, "high": 122, "origin_at": observed},
            "source_zone": {"zone_id": "s1", "distal": 127},
            "reaction_target": {"price": 112},
            "terminal_target_zone": {"low": 104, "high": 108},
            "micro_refinement": {"state": "M5_REFINEMENT_CONFIRMED_SHADOW"},
        },
    }
    rows = _snapshots_from_heartbeats(
        ({"observed_at": observed, "details": {"evaluation": {"m5_path_projection": projection}}},)
    )
    assert rows == ()


def test_v197_enrolls_first_valid_v196_heartbeat_and_no_invalidated_pocket():
    observed = "2026-09-24T06:40:00+00:00"
    projection = {
        "contract": "XAU_BIDIRECTIONAL_M5_PATH_V196",
        "state": "CURRENT_LEG_CANDIDATE_NEXT_LEG_PREMAPPED",
        "current_leg": {
            "direction": "LONG",
            "pocket_state": "CANDIDATE_M5_POCKET",
            "m5_pocket": {"low": 100, "high": 102, "origin_at": observed},
            "source_zone": {"zone_id": "d1", "distal": 95},
            "reaction_target": {"price": 110},
            "terminal_target_zone": {"low": 114, "high": 118},
            "micro_refinement": {"state": "M5_RECLAIM_WAIT_MSS"},
        },
        "next_leg": {
            "direction": "SHORT",
            "source_role": "H1_PRECISION_INSIDE_CURRENT_TERMINAL",
            "pocket_state": "INVALIDATED_M5_POCKET",
            "m5_pocket": {},
            "source_zone": {"zone_id": "s1", "distal": 127},
            "reaction_target": {"price": 112},
            "terminal_target_zone": {"low": 104, "high": 108},
            "micro_refinement": {"state": "SOURCE_INVALIDATED_NO_REFINEMENT"},
        },
    }
    rows = _snapshots_from_heartbeats(
        ({"observed_at": observed, "details": {"evaluation": {"m5_path_projection": projection}}},)
    )
    assert len(rows) == 1
    assert rows[0].leg_role == "current_leg"
    assert rows[0].direction == "LONG"
    assert rows[0].observed_at == datetime(2026, 9, 24, 6, 40, tzinfo=UTC)


def test_v197_preserves_first_enrollment_across_runtime_cycles():
    snap = _snapshot("LONG")
    later = PocketSnapshot(
        episode_key=snap.episode_key,
        observed_at=datetime(2026, 9, 24, 7, 0, tzinfo=UTC),
        leg_role=snap.leg_role,
        direction=snap.direction,
        pocket_state=snap.pocket_state,
        pocket_low=snap.pocket_low,
        pocket_high=snap.pocket_high,
        pocket_origin_at=snap.pocket_origin_at,
        source_role=snap.source_role,
        source_zone=snap.source_zone,
        reaction_target=snap.reaction_target,
        terminal_zone=snap.terminal_zone,
        projection_state=snap.projection_state,
    )
    preserved = _preserve_first_enrollment(
        later,
        {snap.episode_key: datetime(2026, 9, 24, 6, 0, tzinfo=UTC)},
    )
    assert preserved.observed_at == datetime(2026, 9, 24, 6, 0, tzinfo=UTC)


def test_v197_freezes_entire_forecast_geometry_from_existing_ledger_row():
    incoming = _snapshot("LONG")
    incoming = PocketSnapshot(
        episode_key=incoming.episode_key,
        observed_at=datetime(2026, 9, 24, 7, 0, tzinfo=UTC),
        leg_role=incoming.leg_role,
        direction=incoming.direction,
        pocket_state="REFINED_M5_POCKET",
        pocket_low=incoming.pocket_low,
        pocket_high=incoming.pocket_high,
        pocket_origin_at=incoming.pocket_origin_at,
        source_role="NEW_ROLE_SHOULD_NOT_REPLACE",
        source_zone={"zone_id": "source-1", "distal": 93.0, "high": 999.0},
        reaction_target=108.0,
        terminal_zone={"low": 111.0, "high": 150.0},
        projection_state="LATER_RUNTIME_STATE",
    )
    existing = {
        incoming.episode_key: {
            "episode_key": incoming.episode_key,
            "observed_at": "2026-09-24T06:00:00+00:00",
            "direction": "LONG",
            "tp1_price": 110.0,
            "tp2_price": 114.0,
            "metadata": {
                "leg_role": "current_leg",
                "pocket_state_at_enrollment": "CANDIDATE_M5_POCKET",
                "pocket_low": 100.0,
                "pocket_high": 102.0,
                "pocket_origin_at": "2026-09-24T05:55:00+00:00",
                "source_role": None,
                "source_zone": {"zone_id": "source-1", "distal": 95.0},
                "reaction_target": 110.0,
                "terminal_zone": {"low": 114.0, "high": 118.0},
                "projection_state_at_enrollment": "ORIGINAL_STATE",
                "evidence_cohort": "LEGACY_V197_PRE_FREEZE",
                "geometry_frozen_at": "2026-09-24T06:30:00+00:00",
            },
        }
    }

    frozen, cohort, frozen_at = _freeze_snapshot_geometry(
        incoming,
        existing,
        now=datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )

    assert frozen.observed_at == datetime(2026, 9, 24, 6, 0, tzinfo=UTC)
    assert frozen.pocket_state == "CANDIDATE_M5_POCKET"
    assert frozen.source_zone == {"zone_id": "source-1", "distal": 95.0}
    assert frozen.reaction_target == 110.0
    assert frozen.terminal_zone == {"low": 114.0, "high": 118.0}
    assert frozen.projection_state == "ORIGINAL_STATE"
    assert cohort == "LEGACY_V197_PRE_FREEZE"
    assert frozen_at == datetime(2026, 9, 24, 6, 30, tzinfo=UTC)


def test_v197_new_episode_is_strict_immutable_v198_cohort():
    snap = _snapshot("SHORT")
    frozen, cohort, frozen_at = _freeze_snapshot_geometry(
        snap,
        {},
        now=datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
    )
    assert frozen == snap
    assert cohort == "IMMUTABLE_V198"
    assert frozen_at == datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


def test_v197_keeps_pending_ledger_episode_after_projection_disappears():
    snap = _snapshot("LONG")
    existing = {
        snap.episode_key: {
            "episode_key": snap.episode_key,
            "observed_at": snap.observed_at.isoformat(),
            "direction": snap.direction,
            "status": "TOUCHED_PENDING",
            "tp1_price": snap.reaction_target,
            "tp2_price": 114.0,
            "metadata": {
                "leg_role": snap.leg_role,
                "pocket_state_at_enrollment": snap.pocket_state,
                "pocket_low": snap.pocket_low,
                "pocket_high": snap.pocket_high,
                "pocket_origin_at": snap.pocket_origin_at,
                "source_role": snap.source_role,
                "source_zone": snap.source_zone,
                "reaction_target": snap.reaction_target,
                "terminal_zone": snap.terminal_zone,
                "projection_state_at_enrollment": snap.projection_state,
                "evidence_cohort": "IMMUTABLE_V198",
                "geometry_frozen_at": snap.observed_at.isoformat(),
            },
        }
    }
    tracked = _tracked_frozen_states(
        (),
        existing,
        now=datetime(2026, 9, 24, 7, 0, tzinfo=UTC),
        cutoff=datetime(2026, 9, 23, 0, 0, tzinfo=UTC),
    )
    assert len(tracked) == 1
    assert tracked[0][0] == snap
    assert tracked[0][1] == "IMMUTABLE_V198"


def test_v197_does_not_reopen_resolved_episode_from_current_projection():
    snap = _snapshot("LONG")
    existing = {
        snap.episode_key: {
            "episode_key": snap.episode_key,
            "observed_at": snap.observed_at.isoformat(),
            "direction": snap.direction,
            "status": "PROVEN_REACTION_TARGET",
            "tp1_price": snap.reaction_target,
            "tp2_price": 114.0,
            "metadata": {
                "leg_role": snap.leg_role,
                "pocket_state_at_enrollment": snap.pocket_state,
                "pocket_low": snap.pocket_low,
                "pocket_high": snap.pocket_high,
                "source_zone": snap.source_zone,
                "reaction_target": snap.reaction_target,
                "terminal_zone": snap.terminal_zone,
            },
        }
    }
    tracked = _tracked_frozen_states(
        (snap,),
        existing,
        now=datetime(2026, 9, 24, 7, 0, tzinfo=UTC),
        cutoff=datetime(2026, 9, 23, 0, 0, tzinfo=UTC),
    )
    assert tracked == ()

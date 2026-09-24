from datetime import UTC, datetime

from fx_scanner.demo_xau_v201_reaction_ladder import (
    build_reaction_ladder_analytics,
    collapse_physical_pockets,
)
from fx_scanner.models import Bar


def _row(
    key,
    *,
    observed,
    role,
    direction="LONG",
    low=4252.18,
    high=4255.92,
    origin="2026-09-24T11:05:00+00:00",
    zone_id="z1",
    atr=16.0,
    distal=4240.0,
    touch=None,
    status="ENROLLED_WAIT_TOUCH",
    mfe=0.0,
    mae=0.0,
    target=4270.0,
    checkpoint=None,
    strict=True,
):
    return {
        "episode_key": key,
        "observed_at": observed,
        "direction": direction,
        "status": status,
        "first_touch_at": touch,
        "outcome_at": (
            "2026-09-24T15:00:00+00:00"
            if status.startswith("INVALIDATED_")
            else None
        ),
        "tp1_price": target,
        "tp2_price": 4274.39,
        "tp1_hit": False,
        "tp2_hit": False,
        "mfe_points": mfe,
        "mae_points": mae,
        "metadata": {
            "leg_role": role,
            "pocket_low": low,
            "pocket_high": high,
            "pocket_origin_at": origin,
            "reaction_target": target,
            "checkpoint_target": checkpoint,
            "source_zone": {
                "zone_id": zone_id,
                "timeframe": "H1",
                "atr_points": atr,
                "distal": distal,
            },
            "evidence_cohort": (
                "IMMUTABLE_V198" if strict else "LEGACY_V197_PRE_FREEZE"
            ),
            "strict_analytics_eligible": strict,
        },
    }


def _bar(ts, *, open_, high, low, close):
    return Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=datetime.fromisoformat(ts).astimezone(UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        tick_count=10,
        spread_avg=0.2,
        spread_max=0.3,
    )


def test_v201_collapses_next_to_current_same_physical_pocket():
    rows = (
        _row(
            "next",
            observed="2026-09-24T13:03:47+00:00",
            role="next_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            mfe=8.35,
            mae=4.34,
            target=4280.0,
        ),
        _row(
            "current",
            observed="2026-09-24T14:14:55+00:00",
            role="current_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            mfe=8.35,
            mae=4.34,
            target=4270.0,
        ),
    )
    pockets = collapse_physical_pockets(rows)
    assert len(pockets) == 1
    p = pockets[0]
    assert p["first_seen_role"] == "next_leg"
    assert round(p["premap_lead_minutes"], 2) == 91.22
    assert round(p["current_leg_lead_minutes"], 2) == 20.08
    assert p["premapped_before_touch"] is True
    assert p["role_transition_before_touch"] is True
    assert [x["role"] for x in p["target_versions"]] == [
        "next_leg",
        "current_leg",
    ]


def test_v201_4252_example_hits_half_atr_but_not_three_quarter():
    rows = (
        _row(
            "x",
            observed="2026-09-24T14:14:55+00:00",
            role="current_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            atr=16.3554,
            mfe=8.35,
            mae=4.34,
        ),
    )
    p = collapse_physical_pockets(rows)[0]
    ladder = {x["atr_multiple"]: x for x in p["reaction_ladder"]}
    assert ladder[0.25]["hit"] is True
    assert ladder[0.50]["hit"] is True
    assert ladder[0.75]["hit"] is False
    assert ladder[1.00]["hit"] is False


def test_v201_first_hit_timestamps_ignore_pre_touch_and_unfinished_m5():
    rows = (
        _row(
            "chronology",
            observed="2026-09-24T14:14:55+00:00",
            role="current_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="TOUCHED_PENDING",
            atr=16.0,
            mfe=50.0,
        ),
    )
    bars = (
        # This bar would hit every rung but is before the prospective touch.
        _bar(
            "2026-09-24T14:30:00+00:00",
            open_=4254.0,
            high=4305.0,
            low=4253.0,
            close=4300.0,
        ),
        _bar(
            "2026-09-24T14:35:00+00:00",
            open_=4254.0,
            high=4257.90,
            low=4253.0,
            close=4256.0,
        ),
        _bar(
            "2026-09-24T14:40:00+00:00",
            open_=4256.0,
            high=4258.20,
            low=4255.0,
            close=4258.0,
        ),
        _bar(
            "2026-09-24T14:45:00+00:00",
            open_=4258.0,
            high=4262.20,
            low=4257.0,
            close=4261.0,
        ),
        # At 14:58 this 14:55 bar is not completed and must not count.
        _bar(
            "2026-09-24T14:55:00+00:00",
            open_=4261.0,
            high=4305.0,
            low=4260.0,
            close=4300.0,
        ),
    )
    p = collapse_physical_pockets(
        rows,
        bars=bars,
        as_of=datetime(2026, 9, 24, 14, 58, tzinfo=UTC),
    )[0]
    ladder = {x["atr_multiple"]: x for x in p["reaction_ladder"]}

    assert ladder[0.25]["first_hit_at"] == "2026-09-24T14:40:00+00:00"
    assert ladder[0.25]["minutes_from_touch"] == 5.0
    assert ladder[0.50]["first_hit_at"] == "2026-09-24T14:45:00+00:00"
    assert ladder[0.50]["minutes_from_touch"] == 10.0
    assert ladder[0.75]["first_hit_at"] is None
    assert ladder[1.00]["first_hit_at"] is None
    assert ladder[1.00]["chronology_state"] == "CENSORED_PENDING"


def test_v201_same_bar_invalidation_precedes_rung_hit():
    rows = (
        _row(
            "invalidates",
            observed="2026-09-24T14:14:55+00:00",
            role="current_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            atr=16.0,
            distal=4240.0,
            mfe=20.0,
        ),
    )
    bars = (
        _bar(
            "2026-09-24T14:35:00+00:00",
            open_=4254.0,
            high=4257.0,
            low=4253.0,
            close=4255.0,
        ),
        # High crosses 0.25 ATR, but close invalidates the source on same bar.
        _bar(
            "2026-09-24T14:40:00+00:00",
            open_=4255.0,
            high=4260.0,
            low=4238.0,
            close=4239.0,
        ),
    )
    p = collapse_physical_pockets(
        rows,
        bars=bars,
        as_of=datetime(2026, 9, 24, 14, 50, tzinfo=UTC),
    )[0]
    rung = next(x for x in p["reaction_ladder"] if x["atr_multiple"] == 0.25)
    assert rung["hit"] is False
    assert rung["first_hit_at"] is None
    assert rung["chronology_state"] == "RESOLVED_MISS"


def test_v201_target_version_cannot_backfill_before_mapped_at():
    rows = (
        _row(
            "next",
            observed="2026-09-24T13:00:00+00:00",
            role="next_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="TOUCHED_PENDING",
            target=4280.0,
        ),
        _row(
            "current",
            observed="2026-09-24T14:45:00+00:00",
            role="current_leg",
            touch="2026-09-24T14:35:00+00:00",
            status="TOUCHED_PENDING",
            target=4260.0,
        ),
    )
    bars = (
        # Crosses the later current-leg target before that target was mapped.
        _bar(
            "2026-09-24T14:40:00+00:00",
            open_=4255.0,
            high=4265.0,
            low=4254.0,
            close=4262.0,
        ),
        _bar(
            "2026-09-24T14:50:00+00:00",
            open_=4258.0,
            high=4265.0,
            low=4257.0,
            close=4261.0,
        ),
    )
    p = collapse_physical_pockets(
        rows,
        bars=bars,
        as_of=datetime(2026, 9, 24, 15, 0, tzinfo=UTC),
    )[0]
    current_target = next(
        x for x in p["target_versions"] if x["role"] == "current_leg"
    )
    assert current_target["mapped_at"] == "2026-09-24T14:45:00+00:00"
    assert (
        current_target["reaction_first_hit_at"]
        == "2026-09-24T14:50:00+00:00"
    )
    assert current_target["reaction_minutes_from_touch"] == 15.0
    assert current_target["reaction_minutes_from_mapping"] == 5.0


def test_v201_pending_unhit_is_censored_not_failure():
    rows = (
        _row(
            "pending",
            observed="2026-09-24T12:00:00+00:00",
            role="current_leg",
            touch="2026-09-24T12:10:00+00:00",
            status="TOUCHED_PENDING",
            atr=20.0,
            mfe=2.0,
        ),
        _row(
            "resolved",
            observed="2026-09-24T13:00:00+00:00",
            role="current_leg",
            low=4200,
            high=4204,
            origin="2026-09-24T12:50:00+00:00",
            zone_id="z2",
            touch="2026-09-24T13:10:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            atr=20.0,
            mfe=1.0,
        ),
    )
    out = build_reaction_ladder_analytics(rows)
    rung = next(
        x for x in out["strict_ladder"] if x["atr_multiple"] == 0.25
    )
    assert rung["confirmed_hits"] == 0
    assert rung["resolved_misses"] == 1
    assert rung["pending_censored"] == 1
    assert rung["decisive_n"] == 1


def test_v201_hit_pending_counts_as_confirmed_hit():
    rows = (
        _row(
            "pending-hit",
            observed="2026-09-24T12:00:00+00:00",
            role="current_leg",
            touch="2026-09-24T12:10:00+00:00",
            status="TOUCHED_PENDING",
            atr=20.0,
            mfe=6.0,
        ),
    )
    out = build_reaction_ladder_analytics(rows)
    rung = next(
        x for x in out["strict_ladder"] if x["atr_multiple"] == 0.25
    )
    assert rung["confirmed_hits"] == 1
    assert rung["resolved_misses"] == 0
    assert rung["pending_censored"] == 0
    assert rung["precision_decisive"] == 1.0

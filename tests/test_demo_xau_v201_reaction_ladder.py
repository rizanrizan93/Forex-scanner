from fx_scanner.demo_xau_v201_reaction_ladder import (
    build_reaction_ladder_analytics,
    collapse_physical_pockets,
)


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
    touch=None,
    status="ENROLLED_WAIT_TOUCH",
    mfe=0.0,
    mae=0.0,
    target=4270.0,
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
            "source_zone": {
                "zone_id": zone_id,
                "timeframe": "H1",
                "atr_points": atr,
            },
            "evidence_cohort": "IMMUTABLE_V198" if strict else "LEGACY_V197_PRE_FREEZE",
            "strict_analytics_eligible": strict,
        },
    }


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
    assert [x["role"] for x in p["target_versions"]] == ["next_leg", "current_leg"]


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
    rung = next(x for x in out["strict_ladder"] if x["atr_multiple"] == 0.25)
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
    rung = next(x for x in out["strict_ladder"] if x["atr_multiple"] == 0.25)
    assert rung["confirmed_hits"] == 1
    assert rung["resolved_misses"] == 0
    assert rung["pending_censored"] == 0
    assert rung["precision_decisive"] == 1.0

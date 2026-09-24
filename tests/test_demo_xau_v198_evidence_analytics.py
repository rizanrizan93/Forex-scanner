from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_v198_evidence_analytics import (
    build_analytics,
    evaluate_full_path_chain,
    summarize_rows,
)


def _row(
    key,
    *,
    leg_role="current_leg",
    direction="LONG",
    cohort="IMMUTABLE_V198",
    observed="2026-09-24T06:00:00+00:00",
    touch=None,
    reaction=None,
    terminal=None,
    status="ENROLLED_WAIT_TOUCH",
    mfe=0.0,
    mae=0.0,
):
    return {
        "episode_key": key,
        "observed_at": observed,
        "direction": direction,
        "status": status,
        "first_touch_at": touch,
        "outcome_at": terminal or reaction,
        "tp1_hit": reaction is not None,
        "tp2_hit": terminal is not None,
        "mfe_points": mfe,
        "mae_points": mae,
        "metadata": {
            "leg_role": leg_role,
            "pocket_state_at_enrollment": "REFINED_M5_POCKET",
            "source_role": (
                "H1_PRECISION_INSIDE_CURRENT_TERMINAL"
                if leg_role == "next_leg"
                else None
            ),
            "immutable_forecast_geometry": True,
            "strict_analytics_eligible": cohort == "IMMUTABLE_V198",
            "evidence_cohort": cohort,
            "reaction_hit_at": reaction,
            "terminal_hit_at": terminal,
            "source_zone": {
                "session_context": "OTHER_WIB",
                "lifecycle": {"freshness": "FIRST_TEST"},
                "approach": {"state": "CONTROLLED_APPROACH"},
                "liquidity": {"confluence_count": 3},
            },
        },
    }


def test_v198_summary_counts_no_order_shadow_evidence():
    rows = (
        _row(
            "a",
            touch="2026-09-24T06:10:00+00:00",
            reaction="2026-09-24T06:20:00+00:00",
            status="PROVEN_REACTION_TARGET",
            mfe=12,
            mae=2,
        ),
        _row(
            "b",
            touch="2026-09-24T06:15:00+00:00",
            status="INVALIDATED_AFTER_TOUCH",
            mfe=3,
            mae=8,
        ),
        _row("c"),
    )
    out = summarize_rows(rows)
    assert out["enrolled"] == 3
    assert out["touched"] == 2
    assert out["reaction_hits"] == 1
    assert out["reaction_precision_given_touch"] == 0.5
    assert out["invalidated"] == 1
    assert out["median_time_to_touch_minutes"] == 12.5
    assert out["sample_state"] == "COLLECTING"
    assert out["target_80pct_gate_met"] is False


def test_v198_full_path_requires_chronological_sequence():
    current = _row(
        "current",
        leg_role="current_leg",
        touch="2026-09-24T06:10:00+00:00",
        reaction="2026-09-24T06:20:00+00:00",
        status="PROVEN_REACTION_TARGET",
    )
    reverse = _row(
        "reverse",
        leg_role="next_leg",
        direction="SHORT",
        touch="2026-09-24T06:30:00+00:00",
        reaction="2026-09-24T06:40:00+00:00",
        terminal="2026-09-24T06:50:00+00:00",
        status="PROVEN_TERMINAL_ZONE",
    )
    out = evaluate_full_path_chain((current, reverse))
    assert out["stage_score"] == 5
    assert out["state"] == "REVERSE_TERMINAL_PROVEN"
    assert out["strict_chain"] is True


def test_v198_reverse_touch_before_current_reaction_does_not_advance_chain():
    current = _row(
        "current",
        touch="2026-09-24T06:10:00+00:00",
        reaction="2026-09-24T06:30:00+00:00",
        status="PROVEN_REACTION_TARGET",
    )
    reverse = _row(
        "reverse",
        leg_role="next_leg",
        direction="SHORT",
        touch="2026-09-24T06:20:00+00:00",
        reaction="2026-09-24T06:40:00+00:00",
        status="PROVEN_REACTION_TARGET",
    )
    out = evaluate_full_path_chain((current, reverse))
    assert out["stage_score"] == 2
    assert out["state"] == "CURRENT_REACTION_PROVEN"


def test_v198_strict_and_legacy_cohorts_are_separate():
    strict = _row(
        "strict",
        touch="2026-09-24T06:10:00+00:00",
        reaction="2026-09-24T06:20:00+00:00",
        status="PROVEN_REACTION_TARGET",
    )
    legacy = _row(
        "legacy",
        cohort="LEGACY_V197_PRE_FREEZE",
        touch="2026-09-24T06:10:00+00:00",
        reaction="2026-09-24T06:20:00+00:00",
        status="PROVEN_REACTION_TARGET",
    )
    out = build_analytics((strict, legacy))
    assert out["all_evidence"]["enrolled"] == 2
    assert out["strict_immutable_evidence"]["enrolled"] == 1
    assert out["legacy_pre_freeze_evidence"]["enrolled"] == 1
    assert out["strict_segments"]["direction"][0]["value"] == "LONG"

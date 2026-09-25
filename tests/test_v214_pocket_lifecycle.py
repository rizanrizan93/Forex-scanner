from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_v214_pocket_lifecycle import (
    _leg_lifecycle,
    evaluate_lifecycle,
)

ROOT = Path(__file__).resolve().parents[1]


def _projection() -> dict:
    return {
        "current_leg": {
            "direction": "SHORT",
            "pocket_state": "REFINED_M5_POCKET",
            "m5_pocket": {
                "low": 4285.22,
                "high": 4287.38,
                "origin_at": "2026-09-25T02:40:00+00:00",
            },
            "micro_refinement": {
                "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
                "candidate_entry_pocket": {
                    "low": 4292.71,
                    "high": 4295.82,
                    "origin_at": "2026-09-25T01:40:00+00:00",
                },
                "refined_entry_pocket": {
                    "low": 4285.22,
                    "high": 4287.38,
                    "origin_at": "2026-09-25T02:40:00+00:00",
                },
                "sweep": {
                    "at": "2026-09-25T01:40:00+00:00",
                    "price": 4295.82,
                },
                "reclaim_at": "2026-09-25T01:45:00+00:00",
                "mss_at": "2026-09-25T02:45:00+00:00",
                "displacement_at": "2026-09-25T02:45:00+00:00",
            },
            "zone_reuse_v200": {
                "active_candidate_micro_pocket": {
                    "low": 4292.71,
                    "high": 4295.82,
                    "origin_at": "2026-09-25T01:40:00+00:00",
                },
                "active_refined_micro_pocket": {
                    "low": 4285.22,
                    "high": 4287.38,
                    "origin_at": "2026-09-25T02:40:00+00:00",
                },
            },
        },
        "next_leg": {},
    }


def _physical() -> list[dict]:
    return [
        {
            "physical_key": "candidate",
            "direction": "SHORT",
            "pocket_low": 4292.71,
            "pocket_high": 4295.82,
            "first_seen_at": "2026-09-25T01:51:00+00:00",
            "first_touch_at": "2026-09-25T02:05:00+00:00",
            "premapped_before_touch": True,
            "premap_lead_minutes": 14.0,
            "status": "TOUCHED_PENDING",
            "reaction_ladder": [
                {
                    "atr_multiple": 0.25,
                    "hit": True,
                    "first_hit_at": "2026-09-25T02:10:00+00:00",
                    "minutes_from_touch": 5,
                    "chronology_state": "HIT",
                },
                {
                    "atr_multiple": 0.50,
                    "hit": True,
                    "first_hit_at": "2026-09-25T02:35:00+00:00",
                    "minutes_from_touch": 30,
                    "chronology_state": "HIT",
                },
                {
                    "atr_multiple": 0.75,
                    "hit": True,
                    "first_hit_at": "2026-09-25T02:40:00+00:00",
                    "minutes_from_touch": 35,
                    "chronology_state": "HIT",
                },
            ],
        },
        {
            "physical_key": "refined",
            "direction": "SHORT",
            "pocket_low": 4285.22,
            "pocket_high": 4287.38,
            "first_seen_at": "2026-09-25T02:53:40+00:00",
            "first_touch_at": None,
            "premapped_before_touch": False,
            "premap_lead_minutes": None,
            "status": "ENROLLED_WAIT_TOUCH",
            "reaction_ladder": [],
        },
    ]


def test_v214_preserves_initial_candidate_after_refinement() -> None:
    lifecycle = _leg_lifecycle(_projection()["current_leg"], _physical())
    assert lifecycle["initial_pocket"]["low"] == 4292.71
    assert lifecycle["initial_pocket"]["high"] == 4295.82
    assert lifecycle["refined_pocket"]["low"] == 4285.22
    assert lifecycle["refined_pocket"]["high"] == 4287.38

    assert lifecycle["candidate_evidence"]["physical_key"] == "candidate"
    assert lifecycle["refined_evidence"]["physical_key"] == "refined"
    assert lifecycle["candidate_evidence"]["premapped_before_touch"] is True
    assert lifecycle["refined_evidence"]["premapped_before_touch"] is False


def test_v214_measures_candidate_touch_refinement_and_reaction_latency() -> None:
    lifecycle = _leg_lifecycle(_projection()["current_leg"], _physical())
    latency = lifecycle["latency_minutes"]
    assert latency["candidate_map_to_touch"] == 14.0
    assert latency["touch_to_reclaim"] is None
    assert latency["candidate_map_to_refined"] > 60.0

    ladder = lifecycle["reaction_ladder"]
    assert ladder["0.25"]["minutes_from_touch"] == 5
    assert ladder["0.50"]["minutes_from_touch"] == 30
    assert ladder["0.75"]["minutes_from_touch"] == 35


def test_v214_is_shadow_only_and_runs_after_v213() -> None:
    result = evaluate_lifecycle(_projection(), {"latest_physical_pockets": _physical()})
    assert result["execution_influence"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False

    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    v213 = "python -m fx_scanner.demo_xau_v213_post_zone_path"
    v214 = "python -m fx_scanner.demo_xau_v214_pocket_lifecycle"
    assert workflow.index(v213) < workflow.index(v214)


def test_v214_dashboard_keeps_initial_and_refined_pocket_with_wib_lifecycle() -> None:
    text = (ROOT / "streamlit_app.py").read_text()
    assert "INITIAL M5 **{dc_current_leg_direction}** POCKET" in text
    assert "REFINED M5 **{dc_current_leg_direction}** POCKET" in text
    assert "Pocket awal tetap dipertahankan walaupun refined pocket sudah terbentuk." in text
    assert "Lifecycle awal" in text
    assert "Lifecycle refined" in text
    assert "candidate_mapped_at" in text
    assert "first_touch_at" in text
    assert "reclaim_at" in text
    assert "mss_at" in text
    assert "displacement_at" in text

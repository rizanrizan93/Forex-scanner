from pathlib import Path

from fx_scanner.demo_xau_v215_lifecycle_evidence import (
    _stable_signal_key,
    build_events,
)
from fx_scanner.demo_xau_v216_lifecycle_calibration import summarize

ROOT = Path(__file__).resolve().parents[1]


def _leg() -> dict:
    return {
        "direction": "SHORT",
        "pocket_state": "REFINED_M5_POCKET",
        "initial_pocket": {
            "low": 4292.71,
            "high": 4295.82,
            "origin_at": "2026-09-25T01:40:00+00:00",
        },
        "refined_pocket": {
            "low": 4285.22,
            "high": 4287.38,
            "origin_at": "2026-09-25T02:40:00+00:00",
        },
        "candidate_evidence": {
            "physical_key": "physical-candidate",
            "premapped_before_touch": True,
            "premap_lead_minutes": 14.0,
        },
        "refined_evidence": {
            "physical_key": "physical-refined",
            "premapped_before_touch": False,
        },
        "timeline": {
            "candidate_mapped_at": "2026-09-25T01:51:00+00:00",
            "first_touch_at": "2026-09-25T02:05:00+00:00",
            "sweep_at": "2026-09-25T01:40:00+00:00",
            "reclaim_at": "2026-09-25T01:45:00+00:00",
            "mss_at": "2026-09-25T02:45:00+00:00",
            "displacement_at": "2026-09-25T02:45:00+00:00",
            "refined_mapped_at": "2026-09-25T02:53:40+00:00",
        },
        "latency_minutes": {
            "candidate_map_to_touch": 14.0,
            "touch_to_refined": 48.67,
        },
        "reaction_ladder": {
            "0.25": {
                "hit": True,
                "first_hit_at": "2026-09-25T02:10:00+00:00",
                "minutes_from_touch": 5,
                "chronology_state": "HIT",
            },
            "0.50": {
                "hit": True,
                "first_hit_at": "2026-09-25T02:35:00+00:00",
                "minutes_from_touch": 30,
                "chronology_state": "HIT",
            },
            "0.75": {
                "hit": True,
                "first_hit_at": "2026-09-25T02:40:00+00:00",
                "minutes_from_touch": 35,
                "chronology_state": "HIT",
            },
            "1.00": {
                "hit": False,
                "first_hit_at": None,
                "minutes_from_touch": None,
                "chronology_state": "CENSORED_PENDING",
            },
        },
    }


def test_v215_signal_key_is_geometry_stable_not_reconciliation_dependent() -> None:
    leg = _leg()
    key_before = _stable_signal_key("current_leg", leg)
    leg["candidate_evidence"]["physical_key"] = "changed-later"
    key_after = _stable_signal_key("current_leg", leg)
    assert key_before == key_after
    assert key_before is not None and key_before.startswith("V215:")


def test_v215_builds_shadow_lifecycle_event() -> None:
    events = build_events({"current_leg": _leg(), "next_leg": {}})
    assert len(events) == 1
    event = events[0]
    assert event["stage"] == "REFINED_WITH_REACTION"
    assert event["execution_influence"] is False
    assert event["execution_authority"] is False
    assert event["promotion_authority"] is False
    assert event["fingerprint"]


def test_v216_detects_reaction_before_refinement() -> None:
    payload = build_events({"current_leg": _leg(), "next_leg": {}})[0]
    rows = [
        {
            "observed_at": "2026-09-25T02:54:00+00:00",
            "signal_key": payload["signal_key"],
            "payload": payload,
        }
    ]
    result = summarize(rows)
    assert result["episodes"] == 1
    assert result["touched"] == 1
    assert result["refined"] == 1
    assert result["reaction_025_before_refined"]["rate"] == 1.0
    assert result["reaction_050_before_refined"]["rate"] == 1.0
    assert result["candidate_hit_075_given_touch"]["rate"] == 1.0
    assert result["candidate_hit_100_given_touch"]["rate"] == 0.0
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False


def test_v215_v216_run_after_v214_and_dashboard_remains_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    v214 = "python -m fx_scanner.demo_xau_v214_pocket_lifecycle"
    v215 = "python -m fx_scanner.demo_xau_v215_lifecycle_evidence"
    v216 = "python -m fx_scanner.demo_xau_v216_lifecycle_calibration"
    assert workflow.index(v214) < workflow.index(v215) < workflow.index(v216)

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V215/V216 — Candidate vs Refined Calibration" in dashboard
    assert "0.25 ATR sebelum refined" in dashboard
    assert "0.50 ATR sebelum refined" in dashboard
    assert "V215/V216 tetap shadow-only" in dashboard


def test_v216_uses_first_observed_refined_event_not_backdated_timeline() -> None:
    candidate = _leg()
    candidate["refined_pocket"] = {}
    candidate["timeline"]["refined_mapped_at"] = None
    candidate_payload = build_events({"current_leg": candidate, "next_leg": {}})[0]

    refined = _leg()
    refined["initial_pocket"] = dict(candidate["initial_pocket"])
    refined["timeline"]["candidate_mapped_at"] = candidate["timeline"]["candidate_mapped_at"]
    # Simulate the historical bug: timeline claims an early refined time even
    # though the refined label is first observed much later.
    refined["timeline"]["refined_mapped_at"] = "2026-09-25T11:15:21+00:00"
    refined_payload = build_events({"current_leg": refined, "next_leg": {}})[0]

    rows = [
        {
            "observed_at": "2026-09-25T11:16:07+00:00",
            "signal_key": candidate_payload["signal_key"],
            "payload": candidate_payload,
        },
        {
            "observed_at": "2026-09-25T11:43:59+00:00",
            "signal_key": candidate_payload["signal_key"],
            "payload": refined_payload,
        },
    ]
    result = summarize(rows)
    episode = result["episodes_latest"][0]
    assert episode["refined_mapped_at"] == "2026-09-25T11:43:59+00:00"
    assert episode["refined_first_observed_at"] == "2026-09-25T11:43:59+00:00"

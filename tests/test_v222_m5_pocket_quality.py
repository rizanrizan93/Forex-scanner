from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_v222_m5_pocket_quality import (
    _processing_delay_after_close,
    build_quality_evaluation,
)

ROOT = Path(__file__).resolve().parents[1]


def _event(
    key: str,
    *,
    observed_at: str,
    low: float,
    high: float,
    origin_at: str,
    touch_at: str | None = None,
    refined: bool = False,
) -> dict:
    return {
        "observed_at": observed_at,
        "signal_key": key,
        "payload": {
            "role": "current_leg",
            "direction": "SHORT",
            "stage": "REFINED_WAIT_REACTION" if refined else "CANDIDATE_PREMAPPED",
            "initial_pocket": {
                "low": low,
                "high": high,
                "origin_at": origin_at,
            },
            "refined_pocket": (
                {"low": low, "high": high, "origin_at": origin_at}
                if refined else {}
            ),
            "timeline": {
                "candidate_mapped_at": observed_at,
                "first_touch_at": touch_at,
            },
        },
    }


def test_v222_processing_delay_measures_runtime_after_completed_m5() -> None:
    origin = "2026-09-25T11:10:00+00:00"
    mapped = "2026-09-25T11:15:21+00:00"
    delay = _processing_delay_after_close(origin, mapped)
    assert delay is not None
    assert abs(delay - 0.35) < 1e-12


def test_v222_preserves_sequential_pocket_family_and_flags_latest_as_late() -> None:
    events = [
        _event(
            "a",
            observed_at="2026-09-25T11:01:15+00:00",
            low=4309.14,
            high=4311.73,
            origin_at="2026-09-25T10:55:00+00:00",
        ),
        _event(
            "b",
            observed_at="2026-09-25T11:08:18+00:00",
            low=4310.40,
            high=4311.93,
            origin_at="2026-09-25T11:00:00+00:00",
        ),
        _event(
            "c",
            observed_at="2026-09-25T11:15:21+00:00",
            low=4312.59,
            high=4315.82,
            origin_at="2026-09-25T11:10:00+00:00",
            refined=True,
        ),
    ]
    result = build_quality_evaluation(
        events=events,
        lifecycle={"current_leg": {"direction": "SHORT"}},
        atlas_evaluation={
            "last_closed_m15_price": 4304.80,
            "m5_path_projection": {
                "current_leg": {
                    "source_zone": {
                        "zone_id": "parent",
                        "timeframe": "H1",
                        "atr_points": 15.57,
                        "research_score": 69.18,
                        "lifecycle": {"freshness": "DEEPLY_MITIGATED"},
                    }
                }
            },
        },
        calibration_summary={
            "sample_state": "COLLECTING",
            "touched": 5,
            "candidate_hit_025_given_touch": {"n": 5, "hits": 5, "rate": 1.0},
            "candidate_hit_050_given_touch": {"n": 5, "hits": 2, "rate": 0.4},
            "candidate_hit_100_given_touch": {"n": 5, "hits": 2, "rate": 0.4},
        },
        direction_evaluation={
            "tactical_first_leg": {"p_hold_050": 0.58},
        },
        shock_details={"evaluation": {"state": "NORMAL"}},
    )
    assert result["family_count"] == 3
    assert result["family_state"] == "SEQUENTIAL_REMAP_UP"
    latest = result["latest_pocket"]
    assert latest["low"] == 4312.59
    assert latest["timing_state"] == "LATE_FOR_FIRST_ENTRY_WAIT_RETEST"
    assert latest["display_role"] == "RETEST_REFERENCE"
    assert latest["formation_price_was_already_traded"] is True


def test_v222_post_map_touch_is_not_called_late_first_entry() -> None:
    events = [
        _event(
            "a",
            observed_at="2026-09-25T10:34:14+00:00",
            low=4306.17,
            high=4309.63,
            origin_at="2026-09-25T10:25:00+00:00",
            touch_at="2026-09-25T10:35:00+00:00",
        )
    ]
    result = build_quality_evaluation(
        events=events,
        lifecycle={"current_leg": {"direction": "SHORT"}},
        atlas_evaluation={
            "last_closed_m15_price": 4304.8,
            "m5_path_projection": {
                "current_leg": {
                    "source_zone": {
                        "atr_points": 15.57,
                        "research_score": 69.18,
                        "lifecycle": {"freshness": "DEEPLY_MITIGATED"},
                    }
                }
            },
        },
        calibration_summary={},
        direction_evaluation={"tactical_first_leg": {"p_hold_050": 0.58}},
        shock_details={"evaluation": {"state": "NORMAL"}},
    )
    assert result["latest_pocket"]["timing_state"] == "POST_MAP_TOUCH_CONFIRMED"


def test_v222_dashboard_and_workflow_are_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_xau_v222_m5_pocket_quality" in workflow
    assert workflow.index("demo_xau_v216_lifecycle_calibration") < workflow.index(
        "demo_xau_v222_m5_pocket_quality"
    )

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V222 — M5 Pocket Quality & Stability" in dashboard
    assert "LATE_FOR_FIRST_ENTRY_WAIT_RETEST" in dashboard
    assert "V222 tetap shadow-only" in dashboard


def test_v222_uses_actual_first_observed_refined_event() -> None:
    candidate = _event(
        "c",
        observed_at="2026-09-25T11:16:07+00:00",
        low=4312.59,
        high=4315.82,
        origin_at="2026-09-25T11:10:00+00:00",
        refined=False,
    )
    refined = _event(
        "c",
        observed_at="2026-09-25T11:43:59+00:00",
        low=4312.59,
        high=4315.82,
        origin_at="2026-09-25T11:10:00+00:00",
        refined=True,
    )
    # Keep the immutable candidate mapping time in the later refined event.
    refined["payload"]["timeline"]["candidate_mapped_at"] = "2026-09-25T11:15:21+00:00"

    result = build_quality_evaluation(
        events=[candidate, refined],
        lifecycle={"current_leg": {"direction": "SHORT"}},
        atlas_evaluation={
            "last_closed_m15_price": 4304.80,
            "m5_path_projection": {
                "current_leg": {
                    "source_zone": {
                        "atr_points": 15.57,
                        "research_score": 69.18,
                        "lifecycle": {"freshness": "DEEPLY_MITIGATED"},
                    }
                }
            },
        },
        calibration_summary={},
        direction_evaluation={"tactical_first_leg": {"p_hold_050": 0.58}},
        shock_details={"evaluation": {"state": "NORMAL"}},
    )
    latest = result["latest_pocket"]
    assert latest["refined_first_observed_at"] == "2026-09-25T11:43:59+00:00"
    assert latest["candidate_to_refined_observed_minutes"] > 27.8
    assert latest["refinement_timing_state"] == "REFINED_LATE_RETEST_ONLY"

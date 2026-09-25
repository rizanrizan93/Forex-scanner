from datetime import UTC, datetime
from pathlib import Path

from fx_scanner.demo_xau_v217_direction_probability import (
    empirical_leg_distribution,
    evaluate_direction_probability,
    strategic_support_distribution,
)

ROOT = Path(__file__).resolve().parents[1]


def _leg(direction: str) -> dict:
    return {
        "direction": direction,
        "stage": "RECLAIMED_WAIT_MSS",
        "historical_estimate": {
            "p_hold_050": 0.65,
            "p_break": 0.25,
            "p_stall": 0.10,
            "confidence": "HIGH_HISTORICAL_SUPPORT",
            "matched_contracts": 5,
            "estimate_type": "SHRUNK_EMPIRICAL_HOLDOUT_ESTIMATE",
            "median_minutes_to_outcome": 15.0,
        },
    }


def _forecast(score: float = -0.32) -> dict:
    return {
        "ensemble": {
            "directional_prior": {
                "direction": "SHORT" if score < 0 else "LONG",
                "score": score,
            },
            "primary_scenario": {
                "direction": "WAIT_REMAP",
                "structural_path": {
                    "first_leg": "LONG",
                    "continuation": "SHORT",
                },
            },
            "alternative_scenario": {"component_conflict": True},
        }
    }


def test_v217_long_leg_maps_hold_break_and_neutral_exclusively() -> None:
    result = empirical_leg_distribution(_leg("LONG"))
    assert result["p_long"] == 0.65
    assert result["p_short"] == 0.25
    assert abs(result["p_neutral"] - 0.10) < 1e-12
    assert result["normalization"] == "EXCLUSIVE_RESIDUAL"
    assert result["execution_influence"] is False


def test_v217_short_leg_reverses_direction_mapping() -> None:
    result = empirical_leg_distribution(_leg("SHORT"))
    assert result["p_long"] == 0.25
    assert result["p_short"] == 0.65
    assert abs(result["p_neutral"] - 0.10) < 1e-12


def test_v217_strategic_distribution_is_support_not_calibrated_probability() -> None:
    result = strategic_support_distribution(
        _forecast(-0.32),
        {
            "observed_at": "2026-09-25T03:00:00+00:00",
            "details": {
                "evaluation": {
                    "current": {
                        "strategic_bias": "NEUTRAL",
                        "raw_direction": "NEUTRAL",
                    }
                }
            },
        },
        now=datetime(2026, 9, 25, 4, 0, tzinfo=UTC),
    )
    assert result["p_long"] == 0.0
    assert result["p_short"] == 0.32
    assert abs(result["p_neutral"] - 0.68) < 1e-12
    assert result["distribution_type"] == "NORMALIZED_DIRECTIONAL_SUPPORT_NOT_CALIBRATED"
    assert result["not_fully_calibrated_probability_claim"] is True


def test_v217_separates_countertrend_first_leg_from_strategic_continuation() -> None:
    evaluation = evaluate_direction_probability(
        {
            "current_leg": _leg("LONG"),
            "next_leg": _leg("SHORT"),
            "prospective_v197_v198_overlay": {"touched": 15},
        },
        _forecast(-0.32),
        {},
        now=datetime(2026, 9, 25, 4, 0, tzinfo=UTC),
    )
    assert evaluation["state"] == "DIRECTION_PROBABILITY_AVAILABLE"
    assert evaluation["relationship"]["state"] == "COUNTERTREND_FIRST_LEG"
    assert evaluation["relationship"]["sequential_path"] == "LONG_THEN_SHORT"
    assert evaluation["tactical_first_leg"]["p_long"] == 0.65
    assert evaluation["opposing_next_leg"]["p_short"] == 0.65
    assert evaluation["execution_authority"] is False
    assert evaluation["promotion_authority"] is False


def test_v217_workflow_and_dashboard_remain_shadow_only() -> None:
    workflow = (ROOT / ".github/workflows/ctrader-demo-maintenance-pipeline.yml").read_text()
    v216 = "python -m fx_scanner.demo_xau_v216_lifecycle_calibration"
    v217 = "python -m fx_scanner.demo_xau_v217_direction_probability"
    assert workflow.index(v216) < workflow.index(v217)

    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert "V217 — Probabilitas Arah Multi-Horizon" in dashboard
    assert "Strategic HTF support" in dashboard
    assert "Tactical first leg" in dashboard
    assert "V217 tetap shadow-only" in dashboard

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_v226_rizan_depth_map import (
    _break_crossover_band,
    _competing_risk_bands,
    _competing_risk_heatmap,
)
from fx_scanner.xau_reversal_break_forecast_v278 import (
    build_reversal_break_forecast,
)


def _band(name, lo, hi, at_risk, reversals):
    return {
        "band": name,
        "lower_depth": lo,
        "upper_depth": hi,
        "at_risk": at_risk,
        "reversals": reversals,
        "hazard": reversals / at_risk,
    }


def _history() -> dict:
    return {
        "eras": {
            "2025_2026": {
                "summary": {
                    "H1": {
                        "SHORT": {
                            "touches": 100,
                            "holds_050": 55,
                            "breaks": 40,
                            "stalls": 5,
                            "successes_100pct_plus": 1,
                            "hazard_by_depth_band": [
                                _band("00-10%", 0.0, 0.1, 100, 20),
                                _band("10-20%", 0.1, 0.2, 80, 15),
                                _band("20-30%", 0.2, 0.3, 65, 10),
                                _band("30-40%", 0.3, 0.4, 55, 5),
                                _band("40-50%", 0.4, 0.5, 50, 4),
                                _band("50-60%", 0.5, 0.6, 46, 0),
                                _band("60-70%", 0.6, 0.7, 46, 0),
                                _band("70-80%", 0.7, 0.8, 46, 0),
                                _band("80-90%", 0.8, 0.9, 46, 0),
                                _band("90-100%", 0.9, 1.0, 46, 0),
                            ],
                        }
                    }
                }
            }
        }
    }


def _v226(*, touches: int = 0) -> dict:
    profile = {
        "oos_2025_2026_competing_risk_bands": _competing_risk_bands(
            _history(), "H1", "SHORT", era_names=("2025_2026",)
        )
    }
    source = {
        "zone_id": "h1-short",
        "timeframe": "H1",
        "direction": "SHORT",
        "low": 100.0,
        "high": 110.0,
        "distal": 110.0,
        "atr_points": 10.0,
        "lifecycle": {
            "active": True,
            "freshness": "FRESH" if touches == 0 else "FIRST_TEST",
            "touch_count": touches,
        },
    }
    return {
        "focus_direction": "SHORT",
        "depth_entry_candidate": {
            "direction": "SHORT",
            "entry_low": 100.0,
            "entry_high": 101.0,
            "source_zone": source,
            "source_profile": profile,
        },
    }


def _atlas(micro: dict | None = None) -> dict:
    return {
        "path_map": {
            "active_path": {
                "reaction_direction": "SHORT",
                "source_zone": _v226()["depth_entry_candidate"]["source_zone"],
            }
        },
        "micro_refinement": dict(micro or {}),
    }


def test_competing_risk_uses_only_episodes_that_reached_band() -> None:
    rows = _competing_risk_bands(
        _history(), "H1", "SHORT", era_names=("2025_2026",)
    )
    assert rows[0]["at_risk"] == 100
    assert rows[0]["reversal_first"] == 55
    assert rows[0]["break_first"] == 40
    assert rows[0]["unresolved"] == 5
    assert rows[0]["p_reversal_first"] == 0.55
    assert rows[0]["p_break_first"] == 0.40
    # By 40-50%, only 5 reversal outcomes remain from this toy sample, while
    # all 40 distal-close breaks necessarily reached this band.
    assert rows[4]["at_risk"] == 50
    assert rows[4]["reversal_first"] == 5
    assert rows[4]["break_first"] == 40
    assert rows[4]["p_break_first"] > rows[4]["p_reversal_first"]
    assert rows[4]["reversal_wilson_95"]["low"] is not None
    assert rows[4]["break_wilson_95"]["high"] is not None
    assert rows[4]["denominator_contract"] == "EPISODES_THAT_REACHED_BAND_LOWER_BOUND"


def test_competing_risk_crossover_and_heatmap_are_research_only() -> None:
    rows = _competing_risk_bands(
        _history(), "H1", "SHORT", era_names=("2025_2026",)
    )
    crossover = _break_crossover_band(rows)
    assert crossover["band"] in {"30-40%", "40-50%"}
    profile = {"oos_2025_2026_competing_risk_bands": rows}
    heat = _competing_risk_heatmap(
        {"direction": "SHORT", "low": 100.0, "high": 110.0},
        profile,
        oos_only=True,
    )
    assert len(heat) == 10
    assert heat[0]["price_low"] == 100.0
    assert heat[-1]["price_high"] == 110.0
    assert heat[-1]["execution_authority"] is False
    assert heat[-1]["not_current_calibrated_probability"] is True


def test_v278_watch_precedes_m5_confirmation() -> None:
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        direction="SHORT",
        price_now=101.0,
        pressure_transition={
            "state": "BALANCED_ABSORPTION",
            "hard_block": False,
        },
        now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
    )
    assert forecast["stage"] == "REVERSAL_WATCH"
    assert forecast["microstructure"]["reclaim_confirmed"] is False
    assert forecast["entry_demo"]["allowed_by_v278"] is False


def test_v278_reaction_visible_does_not_require_reclaim() -> None:
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(
            {
                "state": "M5_TOUCH_WAIT_RECLAIM",
                "sweep": {"price": 104.0, "at": "2026-09-29T08:59:00+00:00"},
                "candidate_entry_pocket": {"low": 103.0, "high": 104.0},
                "reclaim_confirmed": False,
                "mss_confirmed": False,
                "displacement_confirmed": False,
            }
        ),
        direction="SHORT",
        price_now=104.0,
        pressure_transition={
            "state": "BALANCED_ABSORPTION",
            "hard_block": False,
        },
        now=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
    )
    assert forecast["stage"] == "REAKSI_TERLIHAT"
    assert forecast["reason"] == "SWEEP_OR_REJECTION_POCKET_VISIBLE_WAIT_RECLAIM"


def test_v278_break_risk_requires_live_break_support_not_history_alone() -> None:
    no_live_break = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        direction="SHORT",
        price_now=105.0,
        pressure_transition={"state": "BALANCED_ABSORPTION", "hard_block": False},
    )
    assert no_live_break["competing_risk_reference"]["p_break_first"] > no_live_break["competing_risk_reference"]["p_reversal_first"]
    assert no_live_break["stage"] == "REVERSAL_WATCH"

    live_break = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(),
        direction="SHORT",
        price_now=105.0,
        pressure_transition={"state": "OPPOSING_REACCELERATION", "hard_block": True},
    )
    assert live_break["stage"] == "BREAK_RISK"
    assert live_break["break_risk"]["active"] is True


def test_v278_distal_close_invalidates_without_parent_rescue() -> None:
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas({"state": "SOURCE_INVALIDATED_NO_REFINEMENT"}),
        direction="SHORT",
        price_now=110.2,
        pressure_transition={"state": "OPPOSING_REACCELERATION", "hard_block": True},
    )
    assert forecast["stage"] == "SETUP_INVALID"
    assert "M5_CLOSE_BEYOND_DISTAL" in forecast["break_risk"]["invalidation_reasons"]


def test_v278_no_chase_marks_old_reaction_after_entry_band_left() -> None:
    now = datetime(2026, 9, 29, 9, 30, tzinfo=UTC)
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(
            {
                "state": "M5_TOUCH_WAIT_RECLAIM",
                "sweep": {"price": 101.0, "at": (now - timedelta(minutes=20)).isoformat()},
                "candidate_entry_pocket": {"low": 100.2, "high": 101.0},
            }
        ),
        direction="SHORT",
        price_now=97.0,
        pressure_transition={"state": "BALANCED_ABSORPTION", "hard_block": False},
        v229_plan={"sl": 111.0, "tp2": 90.0, "children": []},
        now=now,
    )
    assert forecast["stage"] == "MISSED_ENTRY_WAIT_NEXT_SETUP"
    assert forecast["no_chase"]["active"] is True
    assert "SELECTED_ENTRY_BAND_ALREADY_LEFT_AFTER_REACTION" in forecast["no_chase"]["reasons"]


def test_v278_retest_never_claims_first_touch_probability_is_current_calibration() -> None:
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(touches=2),
        atlas_evaluation=_atlas(),
        direction="SHORT",
        price_now=101.0,
        pressure_transition={"state": "BALANCED_ABSORPTION", "hard_block": False},
    )
    assert forecast["prior_scope"] == "RETEST_REFERENCE_ONLY_NOT_CALIBRATED"
    assert forecast["competing_risk_reference"]["not_current_calibrated_probability"] is True


def test_v278_entry_stage_requires_v229_authority_and_m5_confirmation() -> None:
    forecast = build_reversal_break_forecast(
        v226_evaluation=_v226(),
        atlas_evaluation=_atlas(
            {
                "state": "M5_MSS_WAIT_DISPLACEMENT",
                "sweep": {"price": 101.0, "at": "2026-09-29T09:00:00+00:00"},
                "candidate_entry_pocket": {"low": 100.0, "high": 101.0},
                "reclaim_confirmed": True,
                "mss_confirmed": True,
                "displacement_confirmed": False,
            }
        ),
        direction="SHORT",
        price_now=100.5,
        pressure_transition={"state": "BALANCED_ABSORPTION", "hard_block": False},
        v229_plan={"sl": 111.0, "tp2": 80.0, "children": []},
        base_entry_authorized=True,
        now=datetime(2026, 9, 29, 9, 1, tzinfo=UTC),
    )
    assert forecast["stage"] == "ENTRY_DEMO_DIIZINKAN"
    assert forecast["entry_demo"]["allowed_by_v278"] is True
    assert forecast["execution_authority"] is False

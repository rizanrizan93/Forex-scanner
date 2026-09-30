from datetime import UTC, datetime

from fx_scanner.xau_reversal_stage_v280 import evaluate_reversal_stage


NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)


def _source(direction="LONG"):
    return {
        "zone_id": "source",
        "timeframe": "H1",
        "direction": direction,
        "low": 100.0,
        "high": 110.0,
        "proximal": 110.0 if direction == "LONG" else 100.0,
        "distal": 100.0 if direction == "LONG" else 110.0,
        "atr_points": 10.0,
        "lifecycle": {"active": True, "freshness": "FIRST_TEST", "touch_count": 1},
    }


def _plan(direction="LONG"):
    return {
        "direction": direction,
        "entry_low": 109.0 if direction == "LONG" else 100.0,
        "entry_high": 110.0 if direction == "LONG" else 101.0,
        "historical_entry_low": 109.0 if direction == "LONG" else 100.0,
        "historical_entry_high": 110.0 if direction == "LONG" else 101.0,
        "rr2": 2.0,
        "broker_entry_authorized": True,
        "candidate": {
            "entry_low": 109.0 if direction == "LONG" else 100.0,
            "entry_high": 110.0 if direction == "LONG" else 101.0,
            "source_zone": _source(direction),
            "zone_reuse": {"historical_prior_scope": "FIRST_TOUCH_PRIOR_GEOMETRY_ONLY"},
        },
    }


def _atlas(micro=None):
    return {
        "micro_refinement": dict(micro or {}),
        "path_map": {"active_path": {"source_zone": _source()}},
    }


def _hazard(depth=0.05, *, execution_ready=True):
    return {
        "state": "DYNAMIC_DEPTH_HAZARD_AVAILABLE",
        "location_state": "INSIDE_ZONE",
        "current_depth": depth,
        "execution_ready": execution_ready,
        "recommended_band": {
            "band": "00-10%",
            "lower_depth": 0.0,
            "upper_depth": 0.10,
            "at_risk": 1000,
            "hazard": 0.20,
        },
    }


def _pressure(*, strict=True, state="BALANCED_ABSORPTION"):
    return {
        "state": state,
        "hard_block": False,
        "calibration_entry_allowed": True,
        "pre_touch_entry_allowed": strict,
        "confirmation_entry_allowed": strict,
    }


def test_v280_reversal_watch_precedes_m5_confirmation() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(),
        depth_hazard=_hazard(),
        pressure_transition=_pressure(strict=False),
        live_price=109.5,
        bid=109.45,
        ask=109.55,
        now=NOW,
    )
    assert stage["stage"] == "REVERSAL_WATCH"
    assert stage["demo_entry_allowed"] is False
    assert stage["calibrated_current_probability"] is False


def test_v280_reaction_visible_before_reclaim_mss() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "sweep": {"price": 108.0, "at": "2026-09-29T14:55:00+00:00"},
                "last_closed_m5_price": 109.5,
                "reclaim_confirmed": False,
                "mss_confirmed": False,
                "displacement_confirmed": False,
            }
        ),
        depth_hazard=_hazard(),
        pressure_transition=_pressure(strict=False),
        live_price=109.5,
        bid=109.45,
        ask=109.55,
        now=NOW,
    )
    assert stage["stage"] == "REACTION_VISIBLE"
    assert stage["reaction_visible"] is True
    assert stage["m5_confirmed"] is False


def test_v280_m5_confirmation_is_visible_before_strict_entry_authority() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "sweep": {"price": 108.0, "at": "2026-09-29T14:55:00+00:00"},
                "last_closed_m5_price": 109.5,
                "reclaim_confirmed": True,
                "mss_confirmed": True,
                "displacement_confirmed": False,
            }
        ),
        depth_hazard=_hazard(execution_ready=False),
        pressure_transition=_pressure(strict=False),
        live_price=109.5,
        bid=109.45,
        ask=109.55,
        now=NOW,
    )
    assert stage["stage"] == "M5_CONFIRMATION"
    assert stage["m5_confirmed"] is True
    assert stage["demo_entry_allowed"] is False


def test_v280_demo_entry_allowed_requires_m5_pressure_depth_and_rr() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "sweep": {"price": 108.0, "at": "2026-09-29T14:55:00+00:00"},
                "last_closed_m5_price": 109.5,
                "reclaim_confirmed": True,
                "mss_confirmed": True,
            }
        ),
        depth_hazard=_hazard(execution_ready=True),
        pressure_transition=_pressure(strict=True),
        live_price=109.5,
        bid=109.45,
        ask=109.55,
        now=NOW,
    )
    assert stage["stage"] == "DEMO_ENTRY_ALLOWED"
    assert stage["demo_entry_allowed"] is True
    assert stage["hard_execution_block"] is False


def test_v280_passed_original_band_is_missed_even_if_m5_confirms_later() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "sweep": {"price": 108.0, "at": "2026-09-29T14:55:00+00:00"},
                "last_closed_m5_price": 108.0,
                "reclaim_confirmed": True,
                "mss_confirmed": True,
            }
        ),
        depth_hazard=_hazard(depth=0.30),
        pressure_transition=_pressure(strict=True),
        live_price=107.0,
        bid=106.95,
        ask=107.05,
        now=NOW,
    )
    assert stage["stage"] == "MISSED_ENTRY_WAIT_NEXT_SETUP"
    assert stage["passed_selected_band"] is True
    assert stage["hard_execution_block"] is True
    assert stage["demo_entry_allowed"] is False


def test_v280_confirmation_window_uses_actual_retest_window_for_no_chase() -> None:
    plan = _plan()
    plan.update(
        {
            "confirmation_window_only": True,
            "confirmation_entry_low": 104.0,
            "confirmation_entry_high": 106.0,
        }
    )
    stage = evaluate_reversal_stage(
        plan=plan,
        atlas_evaluation=_atlas(),
        depth_hazard=_hazard(depth=0.50, execution_ready=False),
        pressure_transition=_pressure(strict=False),
        live_price=105.0,
        bid=104.95,
        ask=105.05,
        now=NOW,
    )
    assert stage["selected_entry_low"] == 104.0
    assert stage["selected_entry_high"] == 106.0
    assert stage["missed_entry"] is False


def test_v280_wick_beyond_distal_is_break_risk_not_immediate_invalidation() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "last_closed_m5_price": 100.2,
                "reclaim_confirmed": False,
                "mss_confirmed": False,
            }
        ),
        depth_hazard=_hazard(depth=1.01),
        pressure_transition=_pressure(strict=False),
        live_price=99.9,
        bid=99.85,
        ask=99.95,
        now=NOW,
    )
    assert stage["stage"] == "BREAK_RISK"
    assert stage["distal"]["live_breach"] is True
    assert stage["distal"]["m5_close_acceptance"] is False
    assert stage["setup_invalid"] is False


def test_v280_m5_close_acceptance_beyond_distal_invalidates_setup() -> None:
    stage = evaluate_reversal_stage(
        plan=_plan(),
        atlas_evaluation=_atlas(
            {
                "last_closed_m5_price": 99.0,
                "reclaim_confirmed": False,
                "mss_confirmed": False,
            }
        ),
        depth_hazard=_hazard(depth=1.05),
        pressure_transition=_pressure(strict=False),
        live_price=99.2,
        bid=99.15,
        ask=99.25,
        now=NOW,
    )
    assert stage["stage"] == "SETUP_INVALID"
    assert stage["setup_invalid"] is True
    assert stage["hard_execution_block"] is True

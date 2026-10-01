from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_outcome_ledger import (
    AUTHORIZED_GEOMETRY_CODES,
    PATH_FORECAST_SETUP_TYPES,
    PREPARED_PLAN_EVENT_TYPES,
    _geometry_authority,
    _grade_for_signal,
    _prepared_by_signal,
    _signal_status,
    _stable_zone_id,
    evaluate_signal_path,
)
from fx_scanner.models import Bar


def _bar(ts, o, h, l, c):
    return Bar("XAUUSD", "M15", ts, o, h, l, c, 1, 0.1, 0.2)


def test_signal_path_short_hits_tp2_before_stop():
    start = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    bars = (
        _bar(start, 4332, 4334, 4325, 4328),
        _bar(start + timedelta(minutes=15), 4328, 4329, 4310, 4315),
    )
    out = evaluate_signal_path(
        bars,
        observed_at=start,
        direction="SHORT",
        entry=4332.0,
        stop=4342.0,
        tp1=4322.0,
        tp2=4312.0,
    )
    assert out.tp1_hit is True
    assert out.tp2_hit is True
    assert out.stop_hit is False
    assert out.outcome_class == "TP2_HIT"
    assert out.mfe_points >= 22.0
    assert out.mfe_r is not None and out.mfe_r >= 2.2


def test_signal_path_same_bar_ambiguity_is_stop_first():
    start = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    bars = (_bar(start, 4332, 4345, 4310, 4330),)
    out = evaluate_signal_path(
        bars,
        observed_at=start,
        direction="SHORT",
        entry=4332.0,
        stop=4342.0,
        tp1=4322.0,
        tp2=4312.0,
    )
    assert out.stop_hit is True
    assert out.tp1_hit is False
    assert out.tp2_hit is False
    assert out.outcome_class == "STOPPED"


def test_nonexecuted_target_hit_becomes_missed_execution():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    path = evaluate_signal_path(
        (_bar(now - timedelta(minutes=15), 4332, 4333, 4310, 4315),),
        observed_at=now - timedelta(minutes=15),
        direction="SHORT",
        entry=4332.0,
        stop=4342.0,
        tp1=4322.0,
        tp2=4312.0,
    )
    status, missed, outcome = _signal_status(
        {"state": "SETUP_FORMING", "expires_at": now.isoformat()},
        path=path,
        order_at=None,
        protection_at=None,
        actual_outcome=None,
        authority="NONE",
        now=now,
    )
    assert status == "MISSED_EXECUTION"
    assert missed is True
    assert outcome == "FORECAST_TARGET_HIT_NO_EXECUTION"


def test_zone_id_is_stable_for_same_structural_zone():
    zone = {
        "direction": "SHORT",
        "origin_at": "2026-09-22T05:00:00+00:00",
        "available_at": "2026-09-22T06:00:00+00:00",
        "low": 4335.07,
        "high": 4342.98,
        "bos_level": 4339.26,
    }
    assert _stable_zone_id(zone) == _stable_zone_id(dict(zone))


def test_target_hit_survives_later_signal_invalidation():
    now = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    path = evaluate_signal_path(
        (
            _bar(now - timedelta(minutes=30), 4335, 4337, 4328, 4330),
            _bar(now - timedelta(minutes=15), 4330, 4331, 4310, 4315),
        ),
        observed_at=now - timedelta(minutes=30),
        direction="SHORT",
        entry=4335.0,
        stop=4345.0,
        tp1=4332.0,
        tp2=4314.0,
    )
    status, missed, outcome = _signal_status(
        {"state": "INVALIDATED", "expires_at": (now + timedelta(hours=1)).isoformat()},
        path=path,
        order_at=None,
        protection_at=None,
        actual_outcome=None,
        authority="NONE",
        now=now,
    )
    assert path.tp2_hit is True
    assert status == "MISSED_EXECUTION"
    assert missed is True
    assert outcome == "FORECAST_TARGET_HIT_NO_EXECUTION"


def test_afic_forecast_waits_for_entry_touch_before_scoring_targets():
    start = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    bars = (
        # Target is already below market, but the SHORT entry at 4335 has not been touched.
        _bar(start, 4305, 4310, 4298, 4302),
        _bar(start + timedelta(minutes=15), 4302, 4320, 4299, 4318),
        # Entry is finally activated here.
        _bar(start + timedelta(minutes=45), 4330, 4337, 4328, 4334),
        _bar(start + timedelta(minutes=60), 4334, 4336, 4310, 4314),
    )
    out = evaluate_signal_path(
        bars,
        observed_at=start,
        direction="SHORT",
        entry=4335.0,
        stop=4345.0,
        tp1=4332.0,
        tp2=4314.0,
        require_entry_touch=True,
    )
    assert out.activation_at == start + timedelta(minutes=45)
    assert out.tp1_hit is True
    assert out.tp2_hit is True
    assert out.outcome_at == start + timedelta(minutes=60)


def test_afic_forecast_without_entry_touch_has_no_target_outcome():
    start = datetime(2026, 9, 22, 20, 0, tzinfo=UTC)
    bars = (
        _bar(start, 4364, 4368, 4359, 4365),
        _bar(start + timedelta(minutes=15), 4365, 4370, 4358, 4368),
    )
    out = evaluate_signal_path(
        bars,
        observed_at=start,
        direction="LONG",
        entry=4345.0,
        stop=4338.0,
        tp1=4348.0,
        tp2=4357.0,
        require_entry_touch=True,
    )
    assert out.activation_at is None
    assert out.tp1_hit is False
    assert out.tp2_hit is False
    assert out.stop_hit is False
    assert out.outcome_at is None
    assert out.outcome_class is None



def test_rizan_contracts_are_first_class_in_outcome_ledger():
    assert "RIZAN_PATH_FORECAST" in PATH_FORECAST_SETUP_TYPES
    assert "DEMO_XAU_RIZAN_PREPARED_PLAN" in PREPARED_PLAN_EVENT_TYPES
    assert "XAU_RIZAN_PATH_EXECUTION_V1" in AUTHORIZED_GEOMETRY_CODES
    assert "XAU_RIZAN_DEPTH_EXECUTION_V1" in AUTHORIZED_GEOMETRY_CODES


def test_prepared_by_signal_accepts_rizan_and_legacy_rows():
    events = (
        {
            "event_type": "DEMO_XAU_RIZAN_PREPARED_PLAN",
            "signal_key": "rizan-1",
            "payload": {"prepared_plan": {"selector_grade": "A"}},
        },
        {
            "event_type": "DEMO_XAU_AFIC_PREPARED_PLAN",
            "signal_key": "legacy-1",
            "payload": {"prepared_plan": {"selector_grade": "B"}},
        },
    )
    prepared = _prepared_by_signal(events)
    assert prepared["rizan-1"]["prepared_plan"]["selector_grade"] == "A"
    assert prepared["legacy-1"]["prepared_plan"]["selector_grade"] == "B"


def test_current_rizan_depth_geometry_is_recognized_as_execution_authority():
    authority = _geometry_authority(
        (
            {
                "event_type": "DEMO_SIGNAL_GEOMETRY",
                "code": "XAU_RIZAN_DEPTH_EXECUTION_V1",
            },
        )
    )
    assert authority == "XAU_RIZAN_DEPTH_EXECUTION_V1"


def test_current_tactical_geometries_are_recognized_as_execution_authority():
    for code in ("IMPULSE_RETEST_V2", "XAU_M15_LIQUIDITY_SWEEP_FADE_V1"):
        assert (
            _geometry_authority(
                ({"event_type": "DEMO_SIGNAL_GEOMETRY", "code": code},)
            )
            == code
        )


def test_rizan_path_forecast_grade_fallback_matches_legacy_thresholds():
    row = {
        "id": "rizan-forecast-1",
        "setup_type": "RIZAN_PATH_FORECAST",
        "final_score": 92.0,
    }
    assert _grade_for_signal(row, {}) == "B"

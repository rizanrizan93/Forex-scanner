from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_outcome_ledger import (
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

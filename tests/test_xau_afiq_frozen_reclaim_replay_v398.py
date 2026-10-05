from __future__ import annotations

from fx_scanner.xau_afiq_frozen_reclaim_replay_v398 import (
    _arm_from_candidate,
    _update_arm,
    _valid_frozen_geometry,
)


def _candidate():
    return {
        "zone_id": "z1",
        "direction": "LONG",
        "entry_reference": 100.0,
        "low": 99.0,
        "high": 101.0,
        "structural_invalidation": 97.0,
        "validation_level": 104.0,
        "targets": [110.0],
        "score": 11.0,
    }


def test_frozen_geometry_requires_target_beyond_validation():
    candidate = _candidate()
    assert _valid_frozen_geometry(candidate)
    candidate["targets"] = [103.0]
    assert not _valid_frozen_geometry(candidate)


def test_reclaim_is_frozen_and_confirms_later():
    arm = _arm_from_candidate(_candidate(), 10)
    assert arm is not None
    assert _update_arm(arm, 102.0, 10) == "ACTIVE"
    assert _update_arm(arm, 103.5, 11) == "ACTIVE"
    assert _update_arm(arm, 104.1, 12) == "CONFIRMED"
    assert arm.validation_level == 104.0


def test_two_acceptance_closes_cancel_arm_before_reclaim():
    arm = _arm_from_candidate(_candidate(), 10)
    assert arm is not None
    assert _update_arm(arm, 96.9, 11) == "ACTIVE"
    assert _update_arm(arm, 96.8, 12) == "INVALIDATED"


def test_arm_expires_without_reclaim():
    arm = _arm_from_candidate(_candidate(), 10)
    assert arm is not None
    assert _update_arm(arm, 102.0, 59) == "EXPIRED"

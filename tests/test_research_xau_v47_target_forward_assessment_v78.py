from datetime import datetime, timedelta, timezone

from fx_scanner.research_xau_v47_target_forward_assessment_v78 import (
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    POLICY_EFFECT,
    PRIMARY_GROUP,
    PROMOTION_ELIGIBLE,
    REFERENCE_GROUP,
    evaluate_target_forward,
)
from fx_scanner.research_xau_v47_target_forward_freeze_v77 import PROSPECTIVE_EPOCH

UTC = timezone.utc


def _evaluation(group: str, index: int):
    return {
        "signal_at": (PROSPECTIVE_EPOCH + timedelta(minutes=15 * index)).isoformat(),
        "v47_approved": True,
        "target_credibility": {
            "target_forward_group": group,
            "target_to_prior60_d1_median": 0.90 if group == PRIMARY_GROUP else 0.60,
        },
    }


def _outcome(index: int, net_r: float):
    return {
        "exit_at": (
            PROSPECTIVE_EPOCH + timedelta(hours=1, minutes=15 * index)
        ).isoformat(),
        "net_r": net_r,
    }


def test_v78_is_shadow_join_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert LIVE_EXECUTION_ENABLED is False
    assert PRIMARY_GROUP == "TARGET_GT_0_75"
    assert REFERENCE_GROUP == "TARGET_LE_0_75"


def test_v78_requires_frozen_forward_sample():
    evaluations = {
        "p0": _evaluation(PRIMARY_GROUP, 0),
        "r0": _evaluation(REFERENCE_GROUP, 1),
    }
    outcomes = {
        "p0": _outcome(0, 1.0),
        "r0": _outcome(1, -0.5),
    }
    result = evaluate_target_forward(evaluations, outcomes)
    assert result["assessment"]["passed"] is False
    assert result["assessment"]["decision"] == "FORWARD_SAMPLE_INSUFFICIENT"
    assert result["primary_target_gt_0_75"]["closed_trades"] == 1
    assert result["reference_target_le_0_75"]["closed_trades"] == 1


def test_v78_can_pass_only_when_both_groups_meet_sample_and_relative_gates():
    evaluations = {}
    outcomes = {}

    # Primary: alternating +1.0 / -0.5 gives PF 4.0, +0.5R expectancy
    # and low drawdown.
    for i in range(30):
        key = f"p{i}"
        evaluations[key] = _evaluation(PRIMARY_GROUP, i)
        outcomes[key] = _outcome(i, 1.0 if i % 3 != 2 else -0.5)

    # Reference: first 15 losses then 15 wins at +/-0.5 => PF 1.0,
    # zero expectancy and materially larger drawdown.
    for i in range(30):
        key = f"r{i}"
        evaluations[key] = _evaluation(REFERENCE_GROUP, 100 + i)
        outcomes[key] = _outcome(100 + i, -0.5 if i < 15 else 0.5)

    result = evaluate_target_forward(evaluations, outcomes)
    assert result["primary_target_gt_0_75"]["closed_trades"] == 30
    assert result["reference_target_le_0_75"]["closed_trades"] == 30
    assert result["assessment"]["passed"] is True
    assert result["assessment"]["decision"] == "READY_FOR_LIMITED_DEMO_EXPERIMENT"


def test_v78_excludes_pre_epoch_and_unavailable_geometry():
    evaluations = {
        "old": {
            "signal_at": (PROSPECTIVE_EPOCH - timedelta(minutes=15)).isoformat(),
            "v47_approved": True,
            "target_credibility": {"target_forward_group": PRIMARY_GROUP},
        },
        "missing": {
            "signal_at": PROSPECTIVE_EPOCH.isoformat(),
            "v47_approved": True,
            "target_credibility": {"target_forward_group": "UNAVAILABLE"},
        },
    }
    result = evaluate_target_forward(evaluations, {})
    assert result["counts"]["excluded_before_epoch"] == 1
    assert result["counts"]["unavailable_geometry"] == 1
    assert result["counts"]["eligible_evaluations"] == 0

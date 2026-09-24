from fx_scanner.demo_xau_zone_reuse_v200 import (
    evaluate_bidirectional_reuse,
    evaluate_zone_reuse,
)


def _zone(*, touches=0, mitigation=0.0, freshness="FRESH", active=True):
    return {
        "zone_id": "z1",
        "direction": "LONG",
        "timeframe": "H1",
        "lifecycle": {
            "touch_count": touches,
            "mitigation_depth": mitigation,
            "freshness": freshness,
            "active": active,
        },
    }


def _micro(*, invalidated=False, refined=True):
    if invalidated:
        return {
            "state": "SOURCE_INVALIDATED_NO_REFINEMENT",
            "mss_confirmed": True,
            "reclaim_confirmed": True,
            "displacement_confirmed": True,
            "refined_entry_pocket": {},
            "candidate_entry_pocket": {"low": 1, "high": 2},
        }
    return {
        "state": "M5_REFINEMENT_CONFIRMED_SHADOW",
        "mss_confirmed": True,
        "reclaim_confirmed": True,
        "displacement_confirmed": True,
        "refined_entry_pocket": {"low": 1, "high": 2} if refined else {},
        "candidate_entry_pocket": {"low": 1, "high": 2},
    }


def test_v200_fresh_zone_has_no_hard_touch_limit_and_no_blind_reuse():
    out = evaluate_zone_reuse(_zone())
    assert out["state"] == "FRESH_PARENT_ZONE"
    assert out["hard_touch_limit"] is None
    assert out["blind_reuse_allowed"] is False
    assert out["fresh_micro_refresh_required"] is False


def test_v200_deep_mitigation_with_invalidated_micro_requires_new_child():
    out = evaluate_zone_reuse(
        _zone(touches=1, mitigation=0.9797, freshness="DEEPLY_MITIGATED"),
        micro_refinement=_micro(invalidated=True),
    )
    assert out["state"] == "DEEPLY_MITIGATED_MICRO_INVALIDATED"
    assert out["fresh_micro_refresh_required"] is True
    assert out["fresh_micro_confirmed"] is False
    assert out["priority"] == "SEARCH_NEW_CHILD_M5"


def test_v200_deep_parent_can_remain_context_when_fresh_micro_reconfirms():
    out = evaluate_zone_reuse(
        _zone(touches=3, mitigation=0.82, freshness="DEEPLY_MITIGATED"),
        micro_refinement=_micro(),
    )
    assert out["state"] == "DEEPLY_MITIGATED_REUSE_WITH_FRESH_MICRO_ONLY"
    assert out["parent_mapping_allowed"] is True
    assert out["fresh_micro_confirmed"] is True


def test_v200_broken_zone_is_retired():
    out = evaluate_zone_reuse(
        _zone(touches=2, mitigation=1.0, freshness="BROKEN", active=False)
    )
    assert out["state"] == "PARENT_ZONE_RETIRED"
    assert out["parent_mapping_allowed"] is False


def test_v200_bidirectional_evaluates_both_legs():
    out = evaluate_bidirectional_reuse(
        {
            "current_leg": {
                "source_zone": _zone(touches=1, mitigation=0.2, freshness="FIRST_TEST"),
                "micro_refinement": {},
            },
            "next_leg": {
                "source_zone": _zone(touches=1, mitigation=0.8, freshness="DEEPLY_MITIGATED"),
                "micro_refinement": _micro(),
            },
        }
    )
    assert out["current_leg"]["state"] == "FIRST_TEST_PARENT_ACTIVE"
    assert out["next_leg"]["state"] == "DEEPLY_MITIGATED_REUSE_WITH_FRESH_MICRO_ONLY"

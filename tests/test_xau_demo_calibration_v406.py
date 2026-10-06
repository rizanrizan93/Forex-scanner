from __future__ import annotations

from fx_scanner.xau_demo_calibration_v406 import build_demo_calibration_candidate_v406


def _v404(*, state: str, grade: str, direction: str) -> dict:
    return {
        "state": state,
        "grade": grade,
        "direction": direction,
        "entry_band": {"low": 4198.0, "high": 4202.0},
        "entry_reference": 4200.0,
        "structural_invalidation": 4190.0 if direction == "LONG" else 4210.0,
        "targets": [4230.0] if direction == "LONG" else [4170.0],
        "rr_first_target": 2.0,
        "liquidity": [{"side": "SELL_SIDE", "price": 4197.0}],
        "event": {},
    }


def _v405(*, state: str, direction: str) -> dict:
    return {
        "state": state,
        "direction": direction,
        "reason": "TEST",
    }


def test_grade_a_promotes_when_v405_is_aligned() -> None:
    out = build_demo_calibration_candidate_v406(
        _v404(state="READY_CONFIRMED", grade="A", direction="LONG"),
        _v405(state="FOCUS_BUY_1", direction="LONG"),
    )
    assert out["eligible"] is True
    assert out["cohort"] == "A"
    assert out["direction"] == "LONG"
    assert out["calibration_policy"]["lot"] == 0.01
    assert out["live_execution_enabled"] is False


def test_grade_a_allows_neutral_v405_map_but_not_conflict() -> None:
    neutral = build_demo_calibration_candidate_v406(
        _v404(state="READY_CONFIRMED", grade="A", direction="LONG"),
        _v405(state="RANGE_MAP", direction="WAIT"),
    )
    assert neutral["eligible"] is True
    assert neutral["cohort"] == "A"

    conflict = build_demo_calibration_candidate_v406(
        _v404(state="READY_CONFIRMED", grade="A", direction="LONG"),
        _v405(state="FOCUS_SELL_1", direction="SHORT"),
    )
    assert conflict["eligible"] is False
    assert conflict["cohort"] == "NONE"


def test_grade_b_requires_v405_alignment() -> None:
    aligned = build_demo_calibration_candidate_v406(
        _v404(state="READY_EARLY", grade="B", direction="SHORT"),
        _v405(state="FOCUS_SELL_1", direction="SHORT"),
    )
    assert aligned["eligible"] is True
    assert aligned["cohort"] == "B"

    neutral = build_demo_calibration_candidate_v406(
        _v404(state="READY_EARLY", grade="B", direction="SHORT"),
        _v405(state="RANGE_MAP", direction="WAIT"),
    )
    assert neutral["eligible"] is False


def test_watch_plus_active_v405_edge_is_separate_c_cohort() -> None:
    out = build_demo_calibration_candidate_v406(
        _v404(state="WATCH_CONFIRMATION", grade="B", direction="LONG"),
        _v405(state="FOCUS_BUY_1", direction="LONG"),
    )
    assert out["eligible"] is True
    assert out["cohort"] == "C"
    assert out["reason"] == "V404_WATCH_PLUS_V405_ACTIVE_EDGE"


def test_hard_blocks_never_promote() -> None:
    for state in (
        "BLOCKED_EVENT",
        "INVALIDATED",
        "WAIT_CONFLICT",
        "WAIT_V403_UNAVAILABLE",
        "UNAVAILABLE",
    ):
        out = build_demo_calibration_candidate_v406(
            _v404(state=state, grade="A", direction="LONG"),
            _v405(state="FOCUS_BUY_1", direction="LONG"),
        )
        assert out["eligible"] is False
        assert out["cohort"] == "NONE"
        assert out["direction"] == "WAIT"


def test_missing_structural_geometry_blocks_candidate() -> None:
    v404 = _v404(state="READY_CONFIRMED", grade="A", direction="LONG")
    v404["structural_invalidation"] = None
    out = build_demo_calibration_candidate_v406(
        v404,
        _v405(state="FOCUS_BUY_1", direction="LONG"),
    )
    assert out["eligible"] is False
    assert out["reason"] == "STRUCTURAL_INVALIDATION_MISSING"

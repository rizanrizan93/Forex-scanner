from datetime import UTC, datetime

from fx_scanner.research_xau_htf_strategic_regime_v180 import RegimePoint
from fx_scanner.research_xau_v229_regime_admission_v243 import (
    EXECUTION_AUTHORITY,
    EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED,
    VARIANT_IDS,
    _latest_regime,
    _regime_payload,
    variant_match,
)
from fx_scanner.research_xau_v229_regime_admission_v243_aggregate import (
    _forward_shadow_screen,
)


def _point(hour: int, bias: str, score: float) -> RegimePoint:
    return RegimePoint(
        map_at=datetime(2026, 1, 1, hour, 0, tzinfo=UTC),
        close=4300.0,
        raw_score=score,
        raw_direction=bias if bias in {"LONG", "SHORT"} else "NEUTRAL",
        strategic_bias=bias,
        baseline_h4_direction="LONG",
        switch_pending_direction=None,
        switch_pending_count=0,
        neutral_pending_count=0,
        components={},
    )


def test_v243_latest_regime_uses_only_map_available_by_plan_time() -> None:
    points = (_point(4, "LONG", 0.20), _point(8, "SHORT", -0.50))
    times = tuple(row.map_at for row in points)
    assert _latest_regime(points, times, datetime(2026, 1, 1, 7, 59, tzinfo=UTC)) == points[0]
    assert _latest_regime(points, times, datetime(2026, 1, 1, 8, 0, tzinfo=UTC)) == points[1]


def test_v243_regime_payload_alignment_and_strong_contract() -> None:
    long = _regime_payload(_point(4, "LONG", 0.50), direction="LONG")
    assert long["alignment"] == "ALIGNED"
    assert long["strong_regime"] is True
    counter = _regime_payload(_point(4, "SHORT", -0.50), direction="LONG")
    assert counter["alignment"] == "COUNTER"


def test_v243_variant_family_is_frozen_and_no_unknown_variant_allowed() -> None:
    assert "REGIME_ALIGNED" in VARIANT_IDS
    assert "REGIME_ALIGNED_H4_CONFIRMATION" in VARIANT_IDS
    row = {
        "alignment": "ALIGNED",
        "candidate_source": "H4",
        "slot": 3,
        "strong_regime": True,
    }
    assert variant_match(row, "REGIME_ALIGNED") is True
    assert variant_match(row, "REGIME_ALIGNED_STRONG") is True
    assert variant_match(row, "REGIME_ALIGNED_H4_SOURCE") is True
    assert variant_match(row, "REGIME_ALIGNED_H4_CONFIRMATION") is True
    assert variant_match(row, "REGIME_ALIGNED_PRETOUCH") is False


def test_v243_forward_shadow_screen_requires_stress_and_all_eras() -> None:
    base = {"completed": 300, "profit_factor_r": 1.20, "expectancy_r": 0.10}
    stress = {"completed": 300, "profit_factor_r": 1.10, "expectancy_r": 0.05}
    eras = {
        "a": {"completed": 100, "profit_factor_r": 1.10, "expectancy_r": 0.05},
        "b": {"completed": 100, "profit_factor_r": 1.05, "expectancy_r": 0.02},
        "c": {"completed": 100, "profit_factor_r": 1.15, "expectancy_r": 0.08},
    }
    assert _forward_shadow_screen(base=base, stress=stress, stress_eras=eras)["passed"] is True
    eras["c"]["expectancy_r"] = -0.01
    assert _forward_shadow_screen(base=base, stress=stress, stress_eras=eras)["passed"] is False


def test_v243_remains_shadow_only() -> None:
    assert EXECUTION_INFLUENCE is False
    assert EXECUTION_AUTHORITY is False
    assert LIVE_EXECUTION_ENABLED is False

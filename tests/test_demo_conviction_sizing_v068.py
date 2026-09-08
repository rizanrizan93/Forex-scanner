from pathlib import Path

import pytest

from fx_scanner.demo_conviction_sizing import MAX_DEMO_LOTS, select_demo_conviction_sizing


def _row(score: float, coverage: float = 0.95, rr2: float = 2.5):
    return {
        "final_score": score,
        "data_coverage": coverage,
        "rr2": rr2,
    }


def test_conviction_sizing_scales_lots_by_quality_tier():
    cases = (
        (_row(55.0), "BASE", 0.01, 0.5),
        (_row(65.0), "B", 0.01, 1.0),
        (_row(75.0, 0.90, 2.0), "B_PLUS", 0.02, 1.5),
        (_row(85.0, 0.95, 2.2), "A", 0.04, 2.0),
        (_row(92.0, 0.92, 2.2), "A_PLUS", 0.06, 2.5),
        (_row(97.0, 0.97, 3.0), "ELITE", 0.10, 3.0),
    )
    assert MAX_DEMO_LOTS == 0.10
    for row, tier, lots, risk in cases:
        sizing = select_demo_conviction_sizing(row)
        assert sizing.tier == tier
        assert sizing.lots == lots
        assert sizing.risk_budget_pct == risk


def test_high_score_cannot_unlock_elite_without_coverage_and_rr():
    sizing = select_demo_conviction_sizing(_row(99.0, 0.90, 2.0))
    assert sizing.tier == "A_PLUS"
    assert sizing.lots == 0.06
    assert sizing.risk_budget_pct == 2.5


def test_runtime_cap_can_reduce_but_not_raise_lot_above_point_one():
    sizing = select_demo_conviction_sizing(
        _row(99.0, 0.99, 3.0),
        max_order_lots=0.04,
        max_risk_pct=1.5,
    )
    assert sizing.tier == "ELITE"
    assert sizing.lots == 0.04
    assert sizing.risk_budget_pct == 1.5


def test_invalid_quality_fails_closed():
    with pytest.raises(ValueError, match="DEMO_CONVICTION_SIZING"):
        select_demo_conviction_sizing({"final_score": None, "data_coverage": 0.95, "rr2": 2.5})


def test_fast_handoff_installs_conviction_sizing_before_demo_executor():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")
    assert "install_demo_conviction_sizing" in source
    assert source.index("install_demo_conviction_sizing()") < source.index("calibration_main()")

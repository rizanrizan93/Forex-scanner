from pathlib import Path

import pytest

from fx_scanner.demo_conviction_sizing import MAX_DEMO_LOTS, MAX_DEMO_RISK_PCT, select_demo_conviction_sizing


def _row(score: float, coverage: float = 0.98, rr2: float = 1.5):
    return {
        "final_score": score,
        "data_coverage": coverage,
        "rr2": rr2,
    }


def test_conviction_sizing_retains_quality_tier_without_scaling_exposure():
    cases = (
        (_row(55.0), "BASE", 0.01, 0.5),
        (_row(65.0), "B", 0.01, 0.5),
        (_row(80.0, 0.90, 1.5), "B_PLUS", 0.01, 0.5),
        (_row(87.0, 0.92, 1.5), "A", 0.01, 0.5),
        (_row(92.0, 0.94, 1.5), "A_PLUS", 0.01, 0.5),
        (_row(95.0, 0.96, 1.5), "ELITE", 0.01, 0.5),
        (_row(98.0, 0.99, 1.5), "ELITE_PLUS", 0.01, 0.5),
    )
    assert MAX_DEMO_LOTS == 0.01
    assert MAX_DEMO_RISK_PCT == 0.5
    for row, tier, lots, risk in cases:
        sizing = select_demo_conviction_sizing(row)
        assert sizing.tier == tier
        assert sizing.lots == lots
        assert sizing.risk_budget_pct == risk


def test_elite_quality_never_raises_exposure():
    sizing = select_demo_conviction_sizing(_row(99.0, 0.97, 1.5))
    assert sizing.tier == "ELITE"
    assert sizing.lots == 0.01
    assert sizing.risk_budget_pct == 0.5


def test_runtime_cap_cannot_raise_exposure_above_demo_ceiling():
    sizing = select_demo_conviction_sizing(
        _row(99.0, 0.99, 1.5),
        max_order_lots=0.20,
        max_risk_pct=1.5,
    )
    assert sizing.tier == "ELITE_PLUS"
    assert sizing.lots == 0.01
    assert sizing.risk_budget_pct == 0.5


def test_invalid_quality_fails_closed():
    with pytest.raises(ValueError, match="DEMO_CONVICTION_SIZING"):
        select_demo_conviction_sizing({"final_score": None, "data_coverage": 0.95, "rr2": 1.5})


def test_fast_handoff_installs_bounded_demo_conviction_sizing():
    source = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")
    assert "DEMO_ORDER_LOT_CAP_CEILING = 0.01" in source
    assert "max_same_symbol_lots" in source
    base = Path("src/fx_scanner/demo_fresh_ready_handoff.py").read_text(encoding="utf-8")
    assert "install_demo_conviction_sizing" in base
    assert "live_unlock=0" in base

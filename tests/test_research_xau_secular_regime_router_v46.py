from pathlib import Path

from fx_scanner.research_xau_secular_regime_router_v46 import (
    COST_R_CAP,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
    SECULAR_MOMENTUM_DAYS,
    SECULAR_SLOPE_DAYS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v46_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v46_secular_contract_is_bounded():
    assert SECULAR_MOMENTUM_DAYS == 252
    assert SECULAR_SLOPE_DAYS == 60
    assert COST_R_CAP == 0.10
    assert len(ROUTES) == 5
    assert "SECULAR_BULL_LONG_L12_L20_COST10" in ROUTES
    assert "SECULAR_BEAR_SHORT_L12_L20_COST10_CONTROL" in ROUTES


def test_v46_does_not_use_calendar_era_or_execution_authority():
    src = (ROOT / "src/fx_scanner/research_xau_secular_regime_router_v46.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_secular_regime_router_v46_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"year_or_era_feature_used": False' in src
    assert '"signal_logic_retuned": False' in src
    assert '"dense_grid_search": False' in src
    assert '"selection_uses_future_outcomes": False' in src

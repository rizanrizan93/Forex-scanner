from pathlib import Path

from fx_scanner.research_xau_adaptive_alpha_activation_v40 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
)
from fx_scanner.research_xau_causal_regime_edge_gate_v47 import (
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v47_is_shadow_only():
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False


def test_v47_reuses_v40_gate_without_retuning():
    assert LOOKBACK_TRADING_DAYS == 126
    assert MIN_COMPLETED_TRADES == 30
    assert MIN_TRAILING_PF == 1.10
    assert MIN_TRAILING_EXPECTANCY_R == 0.05


def test_v47_routes_are_bounded():
    assert ROUTES == (
        "LONG_REACCEL_COST10",
        "SECULAR_BULL_REACCEL_LONG_COST10",
        "SECULAR_BULL_LONG_COST10",
    )


def test_v47_has_no_execution_or_future_leakage_authority():
    src = (ROOT / "src/fx_scanner/research_xau_causal_regime_edge_gate_v47.py").read_text()
    runtime = (
        ROOT / "src/fx_scanner/research_xau_causal_regime_edge_gate_v47_runtime.py"
    ).read_text()
    combined = src + "\n" + runtime
    assert "send_new_order" not in combined
    assert '"gate_thresholds_identical_to_v40": True' in src
    assert '"gate_uses_only_completed_prior_route_family_trades": True' in src
    assert '"cold_start_is_off_until_min_sample": True' in src
    assert '"selection_uses_future_outcomes": False' in src

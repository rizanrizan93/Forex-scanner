from pathlib import Path

from fx_scanner.demo_donchian_contextual_v2 import CORE_VARIANT
from fx_scanner.research_xau_donchian_regime_audit_v83 import (
    DIAGNOSTIC_ONLY,
    EXECUTION_INFLUENCE,
    POLICY_EFFECT,
    PROMOTION_ELIGIBLE,
    ROUTES,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v83_uses_frozen_core_only():
    assert CORE_VARIANT.lookback == 20
    assert CORE_VARIANT.atr_period == 14
    assert CORE_VARIANT.buffer_atr == 0.10
    assert POLICY_EFFECT == "SHADOW_ONLY"
    assert EXECUTION_INFLUENCE is False
    assert PROMOTION_ELIGIBLE is False
    assert DIAGNOSTIC_ONLY is True


def test_v83_routes_are_predeclared_without_grid_search():
    assert ROUTES == (
        "RAW",
        "LONG_ALL",
        "SHORT_ALL",
        "SECULAR_BULL_LONG",
        "SECULAR_BEAR_SHORT",
        "SECULAR_ALIGNED_BOTH",
        "SECULAR_BULL_REACCEL_LONG_1_20",
    )
    src=(ROOT / "src/fx_scanner/research_xau_donchian_regime_audit_v83.py").read_text()
    assert '"parameter_grid_search": False' in src
    assert '"donchian_params_retuned": False' in src
    assert '"route_selected_as_winner": False' in src
    assert "send_new_order" not in src

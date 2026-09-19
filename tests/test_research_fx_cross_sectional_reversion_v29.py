from pathlib import Path

from fx_scanner.research_fx_cross_sectional_reversion_v29 import (
    DIAGNOSTIC_ONLY,FX_SYMBOLS,FREQUENCY_TARGET,VARIANTS,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v29_is_non_xau_bounded_reversion_family():
    assert "XAUUSD" not in FX_SYMBOLS
    assert len(VARIANTS)==6
    assert FREQUENCY_TARGET==5.0
    assert all(v.stretch_atr>=0.75 for v in VARIANTS)


def test_v29_reverses_only_after_stretch():
    source=(ROOT/"src/fx_scanner/research_fx_cross_sectional_reversion_v29.py").read_text()
    assert 'direction = "SHORT"' in source
    assert 'direction = "LONG"' in source
    assert "variant.stretch_atr" in source
    assert DIAGNOSTIC_ONLY is True


def test_v29_is_demo_shadow_only():
    runtime=(ROOT/"src/fx_scanner/research_fx_cross_sectional_reversion_v29_runtime.py").read_text()
    workflow=(ROOT/".github/workflows/ctrader-fx-cross-sectional-reversion-v29.yml").read_text()
    assert "V29_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

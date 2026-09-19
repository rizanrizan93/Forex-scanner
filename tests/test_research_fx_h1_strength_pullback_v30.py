from pathlib import Path
from fx_scanner.research_fx_h1_strength_pullback_v30 import DIAGNOSTIC_ONLY,FX_SYMBOLS,FREQUENCY_TARGET,VARIANTS
ROOT=Path(__file__).resolve().parents[1]

def test_v30_non_xau_and_bounded():
    assert "XAUUSD" not in FX_SYMBOLS
    assert len(VARIANTS)==6
    assert FREQUENCY_TARGET==5.0

def test_v30_requires_h4_trend_and_h1_pullback():
    source=(ROOT/"src/fx_scanner/research_fx_h1_strength_pullback_v30.py").read_text()
    assert 'if direction!=trend: continue' in source
    assert "pullback_tolerance_atr" in source
    assert "float(bar.close)>ema" in source
    assert DIAGNOSTIC_ONLY is True

def test_v30_demo_shadow_only():
    runtime=(ROOT/"src/fx_scanner/research_fx_h1_strength_pullback_v30_runtime.py").read_text()
    workflow=(ROOT/".github/workflows/ctrader-fx-h1-strength-pullback-v30.yml").read_text()
    assert "V30_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

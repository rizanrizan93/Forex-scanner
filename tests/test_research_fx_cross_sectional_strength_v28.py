from pathlib import Path

from fx_scanner.research_fx_cross_sectional_strength_v28 import (
    DIAGNOSTIC_ONLY, FX_SYMBOLS, FREQUENCY_TARGET, VARIANTS,
)

ROOT=Path(__file__).resolve().parents[1]


def test_v28_excludes_xau_and_uses_fx_only():
    assert "XAUUSD" not in FX_SYMBOLS
    assert len(FX_SYMBOLS)==15
    assert len(VARIANTS)==6
    assert FREQUENCY_TARGET==5.0


def test_v28_is_point_in_time_and_development_selected():
    source=(ROOT/"src/fx_scanner/research_fx_cross_sectional_strength_v28.py").read_text()
    assert "log(closes[i] / closes[i - lookback])" in source
    assert "eligible = [x for x in evaluations if x[\"development_passed\"]]" in source
    assert DIAGNOSTIC_ONLY is True
    assert '"promotion_eligible": False' in source


def test_v28_cannot_touch_live_or_xau_authority():
    runtime=(ROOT/"src/fx_scanner/research_fx_cross_sectional_strength_v28_runtime.py").read_text()
    workflow=(ROOT/".github/workflows/ctrader-fx-cross-sectional-strength-v28.yml").read_text()
    assert "V28_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

from pathlib import Path

from fx_scanner.research_xau_h1_m15_m5_trend_v9 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_xau_trend_v9_is_preregistered():
    assert len(VARIANTS) == 8
    assert len({variant.variant_id for variant in VARIANTS}) == 8
    assert {variant.pullback_ema for variant in VARIANTS} == {20, 50}
    assert {variant.trigger_mode for variant in VARIANTS} == {"BASIC_BREAK", "DISPLACEMENT_BREAK"}
    assert {variant.target_r for variant in VARIANTS} == {1.25, 1.5}


def test_xau_trend_v9_is_shadow_only():
    source = (ROOT / "src/fx_scanner/research_xau_h1_m15_m5_trend_v9.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-h1-m15-m5-trend-v9.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

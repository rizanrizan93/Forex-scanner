from pathlib import Path

from fx_scanner.research_xau_m5_regime_breakout_v25 import (
    DIAGNOSTIC_ONLY,
    FINAL_TARGET_MEAN_TRADES_PER_DAY,
    VARIANTS,
)

ROOT = Path(__file__).resolve().parents[1]


def test_v25_preregisters_only_regime_breakout_variants():
    assert len(VARIANTS) == 8
    assert len({x.variant_id for x in VARIANTS}) == 8
    assert FINAL_TARGET_MEAN_TRADES_PER_DAY == 5.0
    source = (ROOT / "src/fx_scanner/research_xau_m5_regime_breakout_v25.py").read_text()
    assert "LIQUIDITY_SWEEP" not in source
    assert "FVG_CONTINUATION" not in source
    assert "EMA_PULLBACK" not in source


def test_v25_context_is_completed_bar_and_diagnostic_only():
    source = (ROOT / "src/fx_scanner/research_xau_m5_regime_breakout_v25.py").read_text()
    assert "bisect_right(closes, close_time)" in source
    assert "mapping[days[i]] = completed[i - 1]" in source
    assert DIAGNOSTIC_ONLY is True
    assert '"promotion_eligible": False' in source


def test_v25_is_demo_shadow_only():
    runtime = (ROOT / "src/fx_scanner/research_xau_m5_regime_breakout_v25_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-m5-regime-breakout-v25.yml").read_text()
    assert "V25_DEMO_ONLY" in runtime
    assert "send_new_order" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

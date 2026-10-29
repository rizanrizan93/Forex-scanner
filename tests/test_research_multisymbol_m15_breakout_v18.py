from pathlib import Path

from fx_scanner.research_multisymbol_m15_breakout_v18 import SYMBOLS, VARIANTS

ROOT = Path(__file__).resolve().parents[1]


def test_v18_is_account_wide_and_preregistered():
    assert len(SYMBOLS) == 9
    assert "XAUUSD" in SYMBOLS
    assert "EURUSD" in SYMBOLS
    assert len(VARIANTS) == 6
    assert len({v.variant_id for v in VARIANTS}) == 6
    source = (ROOT / "src/fx_scanner/research_multisymbol_m15_breakout_v18.py").read_text()
    assert '"mean_trades_per_day_min": 5.0' in source
    assert "account-wide across Tier-A FX/metal instruments" in source


def test_v18_uses_previous_completed_d1_and_completed_h1():
    source = (ROOT / "src/fx_scanner/research_multisymbol_m15_breakout_v18.py").read_text()
    assert "mapping[days[i + 1]] = direction" in source
    assert "bisect_right(h1_closes, signal_close)" in source


def test_v18_is_demo_shadow_only():
    source = (ROOT / "src/fx_scanner/research_multisymbol_m15_breakout_v18.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_multisymbol_m15_breakout_v18_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-multisymbol-m15-breakout-v18.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert "V18_DEMO_ONLY" in runtime
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

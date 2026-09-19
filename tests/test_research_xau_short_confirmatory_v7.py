from pathlib import Path

from fx_scanner.research_xau_short_confirmatory_v7 import FROZEN_VARIANT


ROOT = Path(__file__).resolve().parents[1]


def test_v7_is_one_fixed_short_only_hypothesis():
    assert FROZEN_VARIANT.long_filter is None
    assert FROZEN_VARIANT.short_filter == "NONE"
    assert FROZEN_VARIANT.short_target_r == 1.25
    assert FROZEN_VARIANT.trigger_mode == "BASIC_BREAK"
    assert FROZEN_VARIANT.stop_mode == "M15"
    assert FROZEN_VARIANT.selection_eligible is False


def test_v7_uses_only_locked_holdout_and_is_research_only():
    source = (ROOT / "src/fx_scanner/research_xau_short_confirmatory_v7.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-short-confirmatory-v7.yml").read_text()
    assert "development_bars_locked" in source
    assert "signal.signal_index >= split_index" in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

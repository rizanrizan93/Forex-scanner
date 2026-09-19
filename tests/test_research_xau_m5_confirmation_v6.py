from pathlib import Path

from fx_scanner.research_xau_m5_confirmation_v6 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_xau_m5_confirmation_v6_is_preregistered():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 8
    assert len(set(ids)) == len(ids)
    selecting = [variant for variant in VARIANTS if variant.selection_eligible]
    assert len(selecting) == 7
    assert {variant.trigger_mode for variant in VARIANTS} == {
        "BASIC_BREAK",
        "DISPLACEMENT_BREAK",
    }
    assert {variant.stop_mode for variant in VARIANTS} == {"M15", "M5_LOCAL"}


def test_xau_m5_confirmation_v6_is_research_only():
    source = (ROOT / "src/fx_scanner/research_xau_m5_confirmation_v6.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_m5_confirmation_v6_runtime.py").read_text()
    history = (ROOT / "src/fx_scanner/research_xau_m5_history.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-m5-confirmation-v6.yml").read_text()

    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 300_000" in runtime
    assert 'TIMEFRAME = "M5"' in history
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

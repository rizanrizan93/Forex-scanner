from pathlib import Path

from fx_scanner.research_xau_opening_range_breakout_v10 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_v10_is_preregistered():
    assert len(VARIANTS) == 9
    assert len({v.variant_id for v in VARIANTS}) == 9
    assert {v.entry_mode for v in VARIANTS} == {"DIRECT", "RETEST"}
    assert {v.target_r for v in VARIANTS} == {1.25, 1.5, 2.0}


def test_v10_is_shadow_only():
    source = (ROOT / "src/fx_scanner/research_xau_opening_range_breakout_v10.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-opening-range-breakout-v10.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

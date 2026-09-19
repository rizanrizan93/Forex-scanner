from pathlib import Path

from fx_scanner.research_xau_opening_range_fade_v8 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_xau_opening_range_fade_v8_is_preregistered():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 7
    assert len(set(ids)) == len(ids)
    assert {session for variant in VARIANTS for session in variant.sessions} == {
        "ASIA",
        "US",
    }
    assert {variant.target_r for variant in VARIANTS} == {1.25, 1.5}


def test_xau_opening_range_fade_v8_is_research_only():
    source = (ROOT / "src/fx_scanner/research_xau_opening_range_fade_v8.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-opening-range-fade-v8.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "OPENING_RANGE_BARS = 12" in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

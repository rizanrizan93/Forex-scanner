from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v15_is_single_frozen_confirmatory_hypothesis():
    source = (ROOT / "research" / "xau_d1_c2r1_confirm_v15.py").read_text()
    assert "Variant(cadence_days=2, target_r=1.0)" in source
    assert '"oos_seen_before_v15": False' in source
    assert "BLOCK_SIZE = 5" in source
    assert "BOOTSTRAP_TRIALS = 5000" in source


def test_v15_remains_research_only():
    source = (ROOT / "research" / "xau_d1_c2r1_confirm_v15.py").read_text()
    workflow = (ROOT / ".github/workflows/research-xau-d1-c2r1-confirm-v15.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

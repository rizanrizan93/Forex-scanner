from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v16_is_explicitly_post_hoc_and_non_promotional():
    source = (ROOT / "research" / "xau_d1_staggered_robustness_v16.py").read_text()
    assert 'DIAGNOSTIC_ONLY = True' in source
    assert '"oos_previously_exposed": True' in source
    assert '"promotion_eligible": False' in source
    assert "POST_HOC_DIAGNOSTIC_ONLY" in source


def test_v16_checks_all_staggered_variants_and_current_year():
    source = (ROOT / "research" / "xau_d1_staggered_robustness_v16.py").read_text()
    assert "for variant in v14.VARIANTS" in source
    assert '"2026-01-01", "2026-09-01"' in source
    assert "_quarterly_metrics" in source
    assert "_direction_metrics" in source
    assert "_bootstrap" in source


def test_v16_remains_research_only():
    source = (ROOT / "research" / "xau_d1_staggered_robustness_v16.py").read_text()
    workflow = (ROOT / ".github/workflows/research-xau-d1-staggered-robustness-v16.yml").read_text()
    assert "EXECUTION_INFLUENCE = False" in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

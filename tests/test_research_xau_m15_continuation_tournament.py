from pathlib import Path

from fx_scanner.research_xau_m15_continuation_tournament import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_continuation_tournament_is_preregistered_and_shadow_only():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 6
    assert len(set(ids)) == len(ids)
    assert all(variant.bos_lookback in {12, 20} for variant in VARIANTS)
    assert all(variant.target_r in {1.5, 2.0} for variant in VARIANTS)
    assert all(variant.adx_min == 18.0 for variant in VARIANTS)
    assert {variant.session for variant in VARIANTS} == {"ALL", "ASIA", "US"}


def test_continuation_research_workflow_is_demo_research_only():
    text = (ROOT / ".github/workflows/ctrader-xau-m15-continuation-tournament.yml").read_text()
    assert "pull_request:" in text
    assert 'CTRADER_XAU_M15_RESEARCH_HISTORY_BARS: "50000"' in text
    assert "research_xau_m15_continuation_tournament_runtime" in text
    assert "demo_execution_fresh_ready_handoff" not in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text

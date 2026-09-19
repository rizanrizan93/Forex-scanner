from pathlib import Path

from fx_scanner.research_xau_us_reversal_htf_v4 import (
    H1_MIN_BARS,
    H1_STRUCTURE_WINDOW,
    VARIANTS,
)


ROOT = Path(__file__).resolve().parents[1]


def test_xau_v4_is_preregistered_with_nonselecting_control():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 9
    assert len(set(ids)) == len(ids)
    controls = [variant for variant in VARIANTS if not variant.selection_eligible]
    assert len(controls) == 1
    assert controls[0].htf_filter == "NONE"
    assert {variant.htf_filter for variant in VARIANTS if variant.selection_eligible} == {
        "EMA20_50",
        "EMA20_50_200",
        "STRUCTURE_MATCH",
        "EMA20_50_NOT_OPPOSED",
        "EMA20_50_200_NOT_OPPOSED",
        "EMA20_50_DI",
    }
    assert {variant.target_r for variant in VARIANTS} == {1.25, 1.5, 2.0}


def test_xau_v4_htf_contract_and_execution_isolation():
    assert H1_STRUCTURE_WINDOW == 60
    assert H1_MIN_BARS == 220
    source = (ROOT / "src/fx_scanner/research_xau_us_reversal_htf_v4.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_us_reversal_htf_v4_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-us-reversal-htf-v4.yml").read_text()
    assert 'target_reference_pairs=((SESSION_US, SESSION_EUROPE),)' in source
    assert 'family="REVERSAL"' in source
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 100_000" in runtime
    assert "pull_request:" in workflow
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

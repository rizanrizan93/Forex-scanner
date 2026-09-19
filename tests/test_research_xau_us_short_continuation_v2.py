from pathlib import Path

from fx_scanner.research_xau_us_short_continuation_v2 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_xau_us_short_v2_is_preregistered_before_holdout():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 9
    assert len(set(ids)) == len(ids)
    primary = [variant for variant in VARIANTS if "_US_SHORT_" in variant.variant_id]
    assert len(primary) == 7
    assert all(variant.direction == "SHORT" for variant in primary)
    assert all(variant.session == "US" for variant in primary)
    assert all(variant.selection_eligible for variant in primary)
    assert {variant.target_r for variant in primary} == {1.25, 1.5, 1.75}
    assert {variant.adx_min for variant in primary} == {15.0, 18.0, 22.0}


def test_xau_us_short_v2_keeps_controls_and_execution_isolation():
    controls = [variant for variant in VARIANTS if not variant.selection_eligible]
    assert len(controls) == 2
    assert any(variant.session == "ALL" and variant.direction == "SHORT" for variant in controls)
    assert any(variant.session == "ASIA" and variant.direction == "LONG" for variant in controls)

    source = (ROOT / "src/fx_scanner/research_xau_us_short_continuation_v2.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_us_short_continuation_v2_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-us-short-continuation-v2.yml").read_text()

    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 100_000" in runtime
    assert "pull_request:" in workflow
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

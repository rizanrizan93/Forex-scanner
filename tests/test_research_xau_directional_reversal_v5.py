from pathlib import Path

from fx_scanner.research_xau_directional_reversal_v5 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_directional_reversal_v5_is_preregistered_and_shadow_only():
    ids = [variant.variant_id for variant in VARIANTS]
    assert len(ids) == 7
    assert len(set(ids)) == len(ids)
    selecting = [variant for variant in VARIANTS if variant.selection_eligible]
    assert len(selecting) == 4
    assert any(
        variant.long_filter == "EMA20_50_NOT_OPPOSED"
        and variant.long_target_r == 1.25
        and variant.short_filter == "STRUCTURE_MATCH"
        and variant.short_target_r == 1.50
        for variant in selecting
    )
    assert any(
        variant.short_filter == "EMA20_50_NOT_OPPOSED"
        and variant.short_target_r == 2.00
        for variant in selecting
    )


def test_directional_reversal_v5_uses_200k_history_and_no_execution_path():
    source = (ROOT / "src/fx_scanner/research_xau_directional_reversal_v5.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_directional_reversal_v5_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-directional-reversal-v5.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "HISTORY_BARS = 200_000" in runtime
    assert "pull_request:" in workflow
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

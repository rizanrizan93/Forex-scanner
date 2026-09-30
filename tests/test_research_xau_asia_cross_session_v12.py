from pathlib import Path

from fx_scanner.research_xau_asia_cross_session_v12 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_v12_preregistered_cross_session_rules_are_fixed():
    ids = [row.variant_id for row in VARIANTS]
    assert len(ids) == 8
    assert len(set(ids)) == len(ids)
    assert {row.rule for row in VARIANTS} == {
        "US_SIGN_SYMMETRIC",
        "D1_MATCH_US_MOM",
        "D1_REGIME_US_FADE",
        "D1_LONG_ANY",
        "D1_LONG_US_NEG",
        "D1_LONG_US_POS",
        "D1_SHORT_US_POS",
        "D1_SHORT_US_NEG",
    }


def test_v12_is_shadow_only():
    source = (ROOT / "src/fx_scanner/research_xau_asia_cross_session_v12.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_asia_cross_session_v12_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-asia-cross-session-v12.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

from pathlib import Path

from fx_scanner.research_xau_d1_regime_h1_session_v11 import VARIANTS


ROOT = Path(__file__).resolve().parents[1]


def test_v11_preregisters_session_and_h1_filter_variants():
    ids = [row.variant_id for row in VARIANTS]
    assert len(ids) == 10
    assert len(set(ids)) == len(ids)
    assert {row.session_hour_utc for row in VARIANTS} == {0, 7, 12}
    assert {row.h1_filter for row in VARIANTS} == {
        "NONE",
        "EMA20_50_ALIGN",
        "EMA20_50_NOT_OPPOSED",
    }
    assert all(row.max_hold_bars == 12 for row in VARIANTS)


def test_v11_is_shadow_only_and_does_not_touch_broker_handoff():
    source = (ROOT / "src/fx_scanner/research_xau_d1_regime_h1_session_v11.py").read_text()
    runtime = (ROOT / "src/fx_scanner/research_xau_d1_regime_h1_session_v11_runtime.py").read_text()
    workflow = (ROOT / ".github/workflows/ctrader-xau-d1-regime-h1-session-v11.yml").read_text()
    assert '"policy_effect": "SHADOW_ONLY"' in source
    assert '"execution_influence": False' in source
    assert "demo_execution_fresh_ready_handoff" not in source
    assert "demo_execution_fresh_ready_handoff" not in runtime
    assert "FX_LIVE_TRADING_ENABLED" not in workflow
    assert "I_UNDERSTAND_LIVE_ORDERS" not in workflow

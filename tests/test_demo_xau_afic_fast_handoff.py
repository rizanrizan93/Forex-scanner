from pathlib import Path

from fx_scanner.demo_xau_afic_fresh_ready_handoff import (
    AFIC_EXECUTION_STRATEGY_ID,
    SYMBOL,
    WORKER_NAME,
    _ALLOWED_AFIC_STRATEGIES_BY_SYMBOL,
)

ROOT = Path(__file__).resolve().parents[1]


def test_afic_fast_handoff_is_exact_xau_only_identity():
    assert SYMBOL == "XAUUSD"
    assert AFIC_EXECUTION_STRATEGY_ID == "XAU_AFIC_PATH_EXECUTION_V1"
    assert WORKER_NAME == "ctrader_demo_xau_afic_fast_handoff"
    assert _ALLOWED_AFIC_STRATEGIES_BY_SYMBOL == {
        "XAUUSD": frozenset({"XAU_AFIC_PATH_EXECUTION_V1"})
    }
    wrapper = (ROOT / "src/fx_scanner/demo_xau_afic_fresh_ready_handoff.py").read_text()
    assert "load_afic_demo_project_config" not in wrapper
    assert "base.load_demo_project_config =" not in wrapper


def test_afic_minute_lane_runs_immediate_shared_safety_handoff():
    text = (ROOT / ".github/workflows/ctrader-demo-xau-afic-prepared-lane.yml").read_text()
    assert "demo_xau_afic_prepared_plan_producer" in text
    assert "demo_xau_afic_fresh_ready_handoff" in text
    assert "pytest -q" not in text
    assert 'CTRADER_DEMO_AFIC_EXECUTION_ENABLED: "1"' in text
    assert "CTRADER_DEMO_AUTOTRADE_ENABLED:" in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "20.0"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in text
    assert 'CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT: "20.0"' in text
    assert 'CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT: "50.0"' in text
    assert 'FX_KILL_SWITCH: "0"' in text


def test_afic_fast_handoff_reuses_shared_demo_executor_not_direct_broker_submit():
    text = (ROOT / "src/fx_scanner/demo_xau_afic_fresh_ready_handoff.py").read_text()
    assert "base.main()" in text
    assert "install_exact_strategy_identity_filter" in text
    assert "send_new_order" not in text
    assert "ExecutionRouter" not in text


def test_afic_fast_handoff_observability_is_read_only_for_dashboard():
    wrapper = (ROOT / "src/fx_scanner/demo_xau_afic_fresh_ready_handoff.py").read_text()
    dashboard = (ROOT / "streamlit_app.py").read_text()
    assert 'store.write_heartbeat(' in wrapper
    assert '"live_execution_enabled": False' in wrapper
    assert 'ctrader_demo_xau_afic_fast_handoff' in dashboard
    assert 'h4.metric("Fast handoff", fast_label)' in dashboard


def test_afic_fast_handoff_preserves_canonical_weekday_universe_contract():
    wrapper = (ROOT / "src/fx_scanner/demo_xau_afic_fresh_ready_handoff.py").read_text()
    assert "Preserve the canonical weekday universe contract" in wrapper
    assert "install_afic_execution_identity_filter" in wrapper

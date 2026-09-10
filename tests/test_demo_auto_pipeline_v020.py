from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_auto_pipeline_is_dispatch_only_xau_fast_lane_and_demo_only():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "demo_xau_fast_candidate_producer" in text
    assert "demo_xau_fresh_ready_handoff --limit 10" in text
    assert "demo_structural_profit_protector" in text
    assert text.index("demo_xau_fast_candidate_producer") < text.index(
        "demo_xau_fresh_ready_handoff"
    )
    assert text.index("demo_xau_fresh_ready_handoff") < text.index(
        "demo_structural_profit_protector"
    )
    assert "demo_technical_producer" not in text
    assert "demo_closed_trade_reconciler" not in text
    assert "macro-refresh" not in text
    assert "CTRADER_DEMO_AUTOTRADE_ENABLED" in text
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in text
    assert 'CTRADER_DEMO_TECHNICAL_ONLY: "1"' in text
    assert 'CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER: "1"' in text
    assert 'CTRADER_DEMO_FVG_MAX_AGE_MINUTES: "90"' in text
    assert 'CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS: "30"' in text
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "1"' in text
    assert "CTRADER_DEMO_DEEP_ANALYSIS_TOP" not in text
    assert 'CTRADER_DEMO_FAST_RANKING_MAX_AGE_MINUTES: "20"' in text
    assert 'CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS: "0.20"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in text
    assert 'FX_KILL_SWITCH: "0"' in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_demo_discovery_pipeline_is_xau_only_independent_and_non_executing():
    text = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "demo_xau_technical_producer" in text
    assert "demo_closed_trade_reconciler" in text
    assert "demo_trajectory_finalizer" in text
    assert "demo_normalized_calibration_runner incremental" in text
    assert "demo_xau_v2_forward_scorecard" in text
    assert "demo_normalized_calibration_runner adaptive-v2" in text
    assert "demo_normalized_calibration_runner comparison" in text
    assert "demo_normalized_calibration_runner loss-attribution" in text
    assert "demo_calibration_autotrade" not in text
    assert "demo_xau_fresh_ready_handoff" not in text
    assert "demo_structural_profit_protector" not in text
    assert "continue-on-error: true" in text
    assert 'CTRADER_DISABLE_TOKEN_REFRESH: "1"' in text
    assert "CTRADER_DEMO_DEEP_ANALYSIS_TOP" not in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_macro_refresh_is_manual_only_during_demo_technical_testing():
    text = (ROOT / ".github/workflows/forex-official-macro-refresh.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "macro-refresh" in text
    assert "actions: write" not in text
    assert "ctrader-demo-auto-pipeline" not in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "CTRADER_REFRESH_TOKEN" not in text
    assert "SUPABASE_SECRET_KEY" in text


def test_legacy_autotrade_workflow_remains_manual_only():
    text = (ROOT / ".github/workflows/ctrader-demo-autotrade.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text


def test_all_ephemeral_ctrader_workflows_forbid_token_rotation():
    workflow_dir = ROOT / ".github/workflows"
    names = (
        "ctrader-demo-auto-pipeline.yml",
        "ctrader-demo-discovery-pipeline.yml",
        "ctrader-demo-autotrade.yml",
        "ctrader-demo-order-smoke.yml",
        "ctrader-demo-preflight.yml",
        "ctrader-signal-producer.yml",
        "ctrader-smoke.yml",
    )
    for name in names:
        text = (workflow_dir / name).read_text()
        assert 'CTRADER_TOKEN_STATE_PATH: /tmp/ctrader_tokens.json' in text
        assert 'CTRADER_DISABLE_TOKEN_REFRESH: "1"' in text
        assert "\\n" not in text


def test_demo_auto_supervisor_is_self_renewing_and_dispatches_xau_lanes():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "branches: [main]" in text
    assert "paths:" not in text
    assert 'cron: "7,22,37,52 * * * *"' in text
    assert 'workflows: ["cTrader Demo Technical Heartbeat"]' in text
    assert "github.event_name == 'schedule'" in text
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "cancel-in-progress: true" in text
    assert "actions: write" in text
    assert "seq 1 60" in text
    assert "sleep 60" in text
    assert "fast_cadence_seconds=60" in text
    assert "discovery_check_seconds=60" in text
    assert "universe=XAUUSD" in text
    assert "strategy=IMPULSE_RETEST_V2" in text
    assert "SUPERVISOR_FAST_SKIP_BUSY" in text
    assert "SUPERVISOR_DISCOVERY_SKIP_BUSY" in text
    assert "active_count" in text
    assert "overlap_within_lane=DISABLED" in text
    assert "cross_lane=ENABLED" in text
    assert "ctrader-demo-auto-pipeline.yml" in text
    assert "ctrader-demo-discovery-pipeline.yml" in text
    assert "-f ref=main" in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "CTRADER_REFRESH_TOKEN" not in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_demo_technical_heartbeat_is_hourly_seven_days_and_secret_free():
    text = (ROOT / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()

    assert 'cron: "17 * * * *"' in text
    assert "CTRADER_DEMO_TECHNICAL_HEARTBEAT_OK" in text
    assert "calendar=SEVEN_DAYS" in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "SUPABASE_SECRET_KEY" not in text
    assert "macro-refresh" not in text

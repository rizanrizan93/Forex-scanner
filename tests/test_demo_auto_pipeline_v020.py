from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_auto_pipeline_is_dispatch_only_and_demo_only():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "ctrader-signal-producer" in text
    assert "demo_calibration_autotrade --limit 10" in text
    assert text.index("ctrader-signal-producer") < text.index("demo_calibration_autotrade")
    assert "macro-refresh" not in text
    assert "CTRADER_DEMO_AUTOTRADE_ENABLED" in text
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in text
    assert 'CTRADER_DEMO_TECHNICAL_ONLY: "1"' in text
    assert 'CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER: "1"' in text
    assert 'CTRADER_DEMO_FVG_MAX_AGE_MINUTES: "90"' in text
    assert 'CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS: "30"' in text
    assert 'CTRADER_DEMO_SOLUSD_MAX_SPREAD_PIPS: "120"' in text
    assert 'CTRADER_DEMO_ETHUSD_MAX_SPREAD_PIPS: "100"' in text
    assert 'CTRADER_DEMO_BTCUSD_MAX_SPREAD_PIPS: "2000"' in text
    assert 'CTRADER_DEMO_XTIUSD_MAX_SPREAD_PIPS: "6"' in text
    assert 'FX_KILL_SWITCH: "0"' in text
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


def test_demo_auto_supervisor_is_self_renewing_and_dispatches_without_overlap():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "branches: [main]" in text
    assert "paths:" not in text
    assert 'cron: "7,22,37,52 * * * 1-5"' in text
    assert 'workflows: ["cTrader Demo Technical Heartbeat"]' in text
    assert "github.event_name == 'schedule'" in text
    assert "github.event.workflow_run.event == 'schedule'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "cancel-in-progress: false" in text
    assert "actions: write" in text
    assert "seq 1 30" in text
    assert "sleep 120" in text
    assert "SUPERVISOR_SKIP_BUSY" in text
    assert "active_runs" in text
    assert "overlap=DISABLED" in text
    assert "self_renew_schedule=ENABLED" in text
    assert "ctrader-demo-auto-pipeline.yml/dispatches" in text
    assert "-f ref=main" in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "CTRADER_REFRESH_TOKEN" not in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_demo_technical_heartbeat_is_hourly_and_secret_free():
    text = (ROOT / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()

    assert 'cron: "17 * * * 1-5"' in text
    assert "CTRADER_DEMO_TECHNICAL_HEARTBEAT_OK" in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "SUPABASE_SECRET_KEY" not in text
    assert "macro-refresh" not in text

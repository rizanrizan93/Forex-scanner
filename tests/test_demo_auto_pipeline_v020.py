from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_auto_pipeline_is_weekday_five_minute_demo_only():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()

    assert 'cron: "*/5 * * * 1-5"' in text
    assert "ctrader-signal-producer" in text
    assert "ctrader-demo-autotrade --once --limit 10" in text
    assert text.index("ctrader-signal-producer") < text.index("ctrader-demo-autotrade")
    assert "macro-refresh" not in text
    assert "CTRADER_DEMO_AUTOTRADE_ENABLED" in text
    assert 'FX_KILL_SWITCH: "0"' in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_macro_refresh_is_hourly_and_has_no_broker_execution_secrets():
    text = (ROOT / ".github/workflows/forex-official-macro-refresh.yml").read_text()

    assert 'cron: "7 * * * 1-5"' in text
    assert "macro-refresh" in text
    assert "ctrader-demo-autotrade" not in text
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

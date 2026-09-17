from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_auto_pipeline_is_dispatch_only_five_core_fast_lane_and_demo_only():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "demo_execution_fast_candidate_producer" in text
    assert "demo_execution_fresh_ready_handoff --limit 10" in text
    assert "demo_xau_canonical_position_manager" in text
    assert "demo_five_core_time_exit" in text
    assert text.index("demo_execution_fast_candidate_producer") < text.index(
        "demo_execution_fresh_ready_handoff"
    )
    assert text.index("demo_execution_fresh_ready_handoff") < text.index(
        "demo_xau_canonical_position_manager"
    )
    assert text.index("demo_xau_canonical_position_manager") < text.index(
        "demo_five_core_time_exit"
    )
    assert "demo_closed_trade_reconciler" not in text
    assert "macro-refresh" not in text
    assert "CTRADER_DEMO_AUTOTRADE_ENABLED" in text
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in text
    assert 'CTRADER_DEMO_TECHNICAL_ONLY: "1"' in text
    assert 'CTRADER_DEMO_CALIBRATION_ALLOW_PRETRIGGER: "0"' in text
    assert 'CTRADER_DEMO_FVG_MAX_AGE_MINUTES: "90"' in text
    assert 'CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS: "30"' in text
    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "5"' in text
    assert "CTRADER_DEMO_DEEP_ANALYSIS_TOP" not in text
    assert 'CTRADER_DEMO_FAST_RANKING_MAX_AGE_MINUTES: "20"' in text
    assert 'CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS: "0.20"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in text
    assert 'CTRADER_DEMO_ALLOW_SAME_SYMBOL_STACKING: "1"' in text
    assert 'CTRADER_DEMO_STACK_MIN_SCORE: "50.01"' in text
    assert 'CTRADER_DEMO_STACK_MIN_COVERAGE: "0.80"' in text
    assert 'CTRADER_DEMO_STACK_MIN_RR2: "1.5"' in text
    assert 'CTRADER_DEMO_MAX_SAME_SYMBOL_POSITIONS: "4"' in text
    assert 'CTRADER_DEMO_MIN_STACK_SPACING_SECONDS: "0"' in text
    assert 'CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT: "6.0"' in text
    assert 'CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT: "25.0"' in text
    assert 'CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_ENABLED: "0"' in text
    assert 'CTRADER_DEMO_STRUCTURAL_PROFIT_PROTECT_ENABLED: "0"' in text
    assert 'CTRADER_DEMO_XAU_CANONICAL_POSITION_MANAGER_ENABLED: "1"' in text
    assert 'FX_KILL_SWITCH: "0"' in text
    assert "FX_LIVE_TRADING_ENABLED" not in text
    assert "I_UNDERSTAND_LIVE_ORDERS" not in text


def test_demo_auto_pipeline_keeps_existing_position_protection_alive_on_shadow_producer_failure():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()

    assert "id: produce_five_core" in text
    assert "id: produce_xau_v42" in text
    assert "id: produce_xau_m15_reversal" in text
    assert "id: produce_xau_m15_ema_smc_reclaim" in text
    assert "id: produce_xau_m15_sweep_fade" in text
    assert "id: produce_euraud_gbpaud" in text
    assert "id: repair_existing_protection" in text
    assert "id: execute_fresh_handoff" in text
    assert "id: xau_canonical_manager" in text
    assert "id: pair_time_exit" in text
    assert "id: euraud_gbpaud_chandelier" in text
    assert "id: xau_v42_time_exit" in text
    assert "id: xau_v42_profit_lock" in text
    assert text.count("if: ${{ always() && !cancelled() }}") >= 8

    handoff = text.split("- name: Execute all fresh strategy-authorized DEMO signals", 1)[1]
    handoff = handoff.split("- name: Manage canonical XAU filled positions", 1)[0]
    assert "steps.produce_five_core.outcome == 'success'" in handoff
    assert "steps.produce_xau_m15_ema_smc_reclaim.outcome == 'success'" in handoff
    assert "steps.produce_euraud_gbpaud.outcome == 'success'" in handoff
    assert "steps.repair_existing_protection.outcome == 'success'" in handoff
    assert "steps.produce_xau_v42.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_reversal.outcome == 'success'" not in handoff
    assert "steps.produce_xau_m15_sweep_fade.outcome == 'success'" not in handoff

    assert "CRITICAL_STAGE_FAILED" in text
    assert "XAU_CANONICAL_MANAGER" in text
    assert "new_entry_handoff=BLOCKED protection_maintenance=ATTEMPTED" in text
    assert "CTRADER_DEMO_AUTO_PIPELINE_CRITICAL_STAGES_OK" in text


def test_demo_discovery_pipeline_is_pair_specific_independent_and_non_executing():
    text = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()

    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "demo_execution_technical_producer" in text
    assert "demo_closed_trade_reconciler" in text
    assert "demo_trajectory_finalizer" in text
    assert "demo_normalized_calibration_runner incremental" in text
    assert "demo_xau_v2_forward_scorecard" in text
    assert "demo_eurusd_forward_scorecard" in text
    assert "demo_normalized_calibration_runner adaptive-v2" in text
    assert "demo_normalized_calibration_runner comparison" in text
    assert "demo_normalized_calibration_runner loss-attribution" in text
    assert "demo_calibration_autotrade" not in text
    assert "demo_execution_fresh_ready_handoff" not in text
    assert "demo_structural_profit_protector" not in text
    assert "continue-on-error: true" in text
    assert 'CTRADER_DISABLE_TOKEN_REFRESH: "1"' in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in text
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


def test_legacy_autotrade_workflow_remains_manual_only_and_uses_exact_authority_filter():
    text = (ROOT / ".github/workflows/ctrader-demo-autotrade.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "demo_execution_fresh_ready_handoff --limit 10" in text
    assert "ctrader-demo-autotrade --once" not in text
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in text
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in text
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in text


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


def test_demo_auto_supervisor_has_single_schedule_authority_and_dispatches_five_core_lanes():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-supervisor.yml").read_text()
    assert "workflow_dispatch:" in text
    assert 'cron: "2,7,12,17,22,27,32,37,42,47,52,57 * * * 1-5"' in text
    assert "workflow_run:" not in text
    assert "push:" in text
    assert '".github/workflows/ctrader-demo-auto-supervisor.yml"' in text
    assert '".github/workflows/ctrader-demo-auto-pipeline.yml"' in text
    assert "cancel-in-progress: false" in text
    assert "actions: write" in text
    assert "seq 1 5" in text
    assert "sleep 60" in text
    assert "fast_cadence_seconds=60" in text
    assert "discovery_check_seconds=60" in text
    assert "authority=SCHEDULE_5M" in text
    assert "push_kick=SUPERVISOR_OR_AUTO_PIPELINE" in text
    assert "head_sha=${GITHUB_SHA}" in text
    assert "self_handoff=DISABLED" in text
    assert "CTRADER_DEMO_SUPERVISOR_HANDOFF" not in text
    assert "dispatch_workflow ctrader-demo-auto-supervisor.yml" not in text
    assert "universe=XAUUSD,EURUSD,GBPUSD,USDJPY,AUDUSD" in text
    assert "strategies=FIVE_CORE_ROUTER_V1" in text
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


def test_demo_technical_heartbeat_is_hourly_weekdays_and_secret_free():
    text = (ROOT / ".github/workflows/ctrader-demo-technical-heartbeat.yml").read_text()
    assert 'cron: "17 * * * 1-5"' in text
    assert "CTRADER_DEMO_TECHNICAL_HEARTBEAT_OK" in text
    assert "calendar=WEEKDAY_24X5" in text
    assert "CTRADER_CLIENT_SECRET" not in text
    assert "CTRADER_ACCESS_TOKEN" not in text
    assert "SUPABASE_SECRET_KEY" not in text
    assert "macro-refresh" not in text

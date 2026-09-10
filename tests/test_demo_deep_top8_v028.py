from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_active_demo_fast_lane_is_explicitly_xau_only_and_process_local():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    calibration = (ROOT / "src/fx_scanner/demo_calibration.py").read_text()
    wrapper = (ROOT / "src/fx_scanner/demo_xau_fast_candidate_producer.py").read_text()
    strategy = (ROOT / "config/strategy.yaml").read_text()

    assert 'CTRADER_DEMO_FAST_MAX_SYMBOLS: "1"' in workflow
    assert 'CTRADER_DEMO_DEEP_ANALYSIS_TOP: "1"' in workflow
    assert "apply_demo_deep_analysis_top" in calibration
    assert "CTRADER_DEMO_FAST_MAX_SYMBOLS" in wrapper
    assert '"1"' in wrapper
    # Canonical research configuration remains intact; XAU narrowing is DEMO process-local.
    assert "deep_analysis_top: 5" in strategy


def test_xau_fast_lane_keeps_non_structure_execution_guards():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    handoff = (ROOT / "src/fx_scanner/demo_fresh_ready_handoff.py").read_text()
    strategy = (ROOT / "config/strategy.yaml").read_text()

    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert 'CTRADER_DEMO_CHASE_BLOCK_ATR: "2.0"' in workflow
    assert "chase_block_atr: 0.50" in strategy
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in workflow
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in workflow
    assert "broker_native_risk=1" in handoff
    assert "live_unlock=0" in handoff

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_deep_top8_is_explicit_and_process_local():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    calibration = (ROOT / "src/fx_scanner/demo_calibration.py").read_text()
    producer = (ROOT / "src/fx_scanner/demo_technical_producer.py").read_text()
    strategy = (ROOT / "config/strategy.yaml").read_text()

    assert 'CTRADER_DEMO_DEEP_ANALYSIS_TOP: "8"' in workflow
    assert "apply_demo_deep_analysis_top" in calibration
    assert "requested <= min(10, universe)" in calibration
    assert "deep_analysis_top={demo_deep_top}" in producer
    assert "deep_analysis_top: 5" in strategy


def test_demo_deep_top8_keeps_non_structure_execution_guards():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    producer = (ROOT / "src/fx_scanner/demo_technical_producer.py").read_text()
    strategy = (ROOT / "config/strategy.yaml").read_text()

    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert 'CTRADER_DEMO_CHASE_BLOCK_ATR: "2.0"' in workflow
    assert "production_chase_block_atr" in producer
    assert "chase_block_atr: 0.50" in strategy
    assert "hard_guards=ENFORCED" in producer
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "1.0"' in workflow

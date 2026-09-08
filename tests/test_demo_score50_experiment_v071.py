from pathlib import Path


STRATEGY = Path("src/fx_scanner/demo_technical_strategy.py").read_text()
WORKFLOW = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()


def test_score50_experiment_promotes_valid_plan_without_strategy_timing_vetoes():
    assert "_DEMO_SCORE50_RETAINED_BLOCKERS" in STRATEGY
    assert '"SPREAD_BLOCK"' in STRATEGY
    assert '"CORRELATION_BLOCK"' in STRATEGY
    assert '"RISK_BLOCK"' in STRATEGY
    assert '"STALE_SIGNAL"' in STRATEGY
    assert '"DATA_QUALITY_BLOCK"' in STRATEGY
    assert "score50_ready = bool(" in STRATEGY
    assert "and experiment_plan_ready" in STRATEGY
    assert "and not retained_blockers" in STRATEGY
    assert "decision = replace(decision, state=state, guards=retained_blockers)" in STRATEGY


def test_score50_experiment_does_not_remove_account_risk_contracts():
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in WORKFLOW
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "3.0"' in WORKFLOW
    assert 'CTRADER_DEMO_MAX_OPEN_POSITIONS: "10"' in WORKFLOW
    assert 'CTRADER_DEMO_CORRELATION_THRESHOLD: "0.85"' in WORKFLOW

from pathlib import Path


STRATEGY = Path("src/fx_scanner/demo_technical_strategy.py").read_text()
WORKFLOW = Path(".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()


def test_score50_floor_cannot_discard_strategy_timing_or_hard_guard_vetoes():
    assert "_DEMO_SCORE50_RETAINED_BLOCKERS" not in STRATEGY
    assert "score50_ready = bool(" not in STRATEGY
    assert "if not decision.guards:" in STRATEGY
    assert "calibration_ready = bool(" in STRATEGY
    assert "and plan_ready" in STRATEGY
    assert "and early_structure" in STRATEGY
    assert "and fresh_fvg" in STRATEGY


def test_score50_experiment_keeps_runtime_floor_and_risk_ceiling_contracts():
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in WORKFLOW
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "3.0"' in WORKFLOW
    assert "decision.guards" in STRATEGY

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_demo_correlation_guard_retains_fail_closed_upper_bound():
    source = (ROOT / "src/fx_scanner/demo_correlation_evidence.py").read_text(encoding="utf-8")
    assert "MAX_DEMO_RISK_PCT = 5.0" in source
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT must be in (0,5]' in source


def test_fast_pipeline_requests_five_percent_contract():
    workflow = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text(encoding="utf-8")
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "5.0"' in workflow
    assert 'CTRADER_DEMO_MAX_CONCURRENT_POSITIONS: "10"' in workflow
    assert 'CTRADER_DEMO_MAX_ORDER_LOTS: "0.50"' in workflow

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pair_specific_discovery_has_no_weekend_crypto_fallback():
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()

    assert 'CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS: "30"' in workflow
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "3.0"' in workflow
    assert "demo_execution_technical_producer" in workflow
    assert "demo_crypto_broker_preflight" not in workflow
    assert "CTRADER_DEMO_BTCUSD_MAX_SPREAD_PIPS" not in workflow
    assert "CTRADER_DEMO_ETHUSD_MAX_SPREAD_PIPS" not in workflow
    assert "CTRADER_DEMO_SOLUSD_MAX_SPREAD_PIPS" not in workflow
    assert 'date -u +%u' not in workflow

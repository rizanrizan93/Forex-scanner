from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_weekend_discovery_clears_only_inactive_weekday_spread_overrides():
    workflow = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()

    assert 'date -u +%u' in workflow
    assert 'export CTRADER_DEMO_XAUUSD_MAX_SPREAD_PIPS=""' in workflow
    assert 'export CTRADER_DEMO_XTIUSD_MAX_SPREAD_PIPS=""' in workflow
    assert 'CTRADER_DEMO_BTCUSD_MAX_SPREAD_PIPS: "2000"' in workflow
    assert 'CTRADER_DEMO_ETHUSD_MAX_SPREAD_PIPS: "100"' in workflow
    assert 'CTRADER_DEMO_SOLUSD_MAX_SPREAD_PIPS: "120"' in workflow
    assert 'CTRADER_DEMO_EXECUTION_CANDIDATE_MIN: "50.01"' in workflow
    assert 'CTRADER_DEMO_RISK_PER_TRADE_PCT: "1.0"' in workflow

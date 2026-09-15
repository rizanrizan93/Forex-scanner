from pathlib import Path


def test_broker_risk_probe_is_explicitly_no_order():
    source = Path("src/fx_scanner/demo_broker_risk_probe.py").read_text(encoding="utf-8")
    assert "no_order=1 live_unlock=0" in source
    assert "place_order" not in source
    assert "NewOrderReq" not in source
    assert "amend_position" not in source
    assert "close_position" not in source


def test_probe_forces_cross_currency_conversion_contract():
    source = Path("src/fx_scanner/demo_broker_risk_probe.py").read_text(encoding="utf-8")
    assert 'PROBE_SYMBOL = "EURJPY"' in source
    assert "_conversion_chain(session, quote_asset_id, deposit_asset_id)" in source
    assert "_expected_margin_deposit(" in source
    assert "monetary_loss_at_stop(" in source


def test_probe_workflow_is_scoped_to_risk_code_changes():
    source = Path(".github/workflows/ctrader-demo-broker-risk-probe.yml").read_text(encoding="utf-8")
    assert 'branches: [main]' in source
    assert 'src/fx_scanner/demo_broker_risk_sizing.py' in source
    assert 'src/fx_scanner/demo_broker_risk_probe.py' in source
    assert 'python -m fx_scanner.demo_broker_risk_probe' in source

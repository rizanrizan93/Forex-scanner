from fx_scanner.demo_runtime_heartbeat import _runtime_policy_details


def test_runtime_policy_details_expose_bounded_demo_contract(monkeypatch):
    monkeypatch.setenv("CTRADER_DEMO_MAX_ORDER_LOTS", "0.50")
    monkeypatch.setenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "20.0")
    monkeypatch.setenv("CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT", "20.0")
    monkeypatch.setenv("CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT", "50.0")
    monkeypatch.setenv("CTRADER_DEMO_MAX_CONCURRENT_POSITIONS", "10")

    assert _runtime_policy_details() == {
        "max_order_lots": 0.50,
        "max_risk_pct": 20.0,
        "portfolio_risk_cap_pct": 20.0,
        "margin_free_usage_cap_pct": 50.0,
        "max_concurrent_positions": 10,
    }


def test_runtime_policy_details_omit_missing_or_invalid_values(monkeypatch):
    for name in (
        "CTRADER_DEMO_MAX_ORDER_LOTS",
        "CTRADER_DEMO_RISK_PER_TRADE_PCT",
        "CTRADER_DEMO_MAX_PORTFOLIO_RISK_PCT",
        "CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT",
        "CTRADER_DEMO_MAX_CONCURRENT_POSITIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CTRADER_DEMO_MAX_MARGIN_FREE_USAGE_PCT", "invalid")
    assert _runtime_policy_details() == {}

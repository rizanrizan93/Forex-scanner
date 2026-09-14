import os

from fx_scanner.demo_fresh_ready_handoff import (
    DEMO_ACTIVE_ORDER_LOT_CAP,
    DEMO_ACTIVE_RISK_CAP_PCT,
    DEMO_ORDER_LOT_CAP_ENV,
    DEMO_RISK_ENV,
    install_bounded_demo_process_contract,
    load_bounded_demo_execution_policy,
)


def test_active_demo_handoff_hard_caps_lot_and_risk(monkeypatch):
    monkeypatch.setenv(DEMO_ORDER_LOT_CAP_ENV, "0.50")
    monkeypatch.setenv(DEMO_RISK_ENV, "5.0")

    install_bounded_demo_process_contract()
    policy = load_bounded_demo_execution_policy()

    assert os.environ[DEMO_ORDER_LOT_CAP_ENV] == "0.01"
    assert os.environ[DEMO_RISK_ENV] == "3.0"
    assert policy.demo_safety["max_order_lots"] == DEMO_ACTIVE_ORDER_LOT_CAP == 0.01
    assert policy.demo_safety["max_risk_pct"] == DEMO_ACTIVE_RISK_CAP_PCT == 3.0
    assert policy.demo_safety["max_concurrent_positions"] == 10


def test_active_demo_handoff_does_not_mutate_entry_geometry_contract():
    policy = load_bounded_demo_execution_policy()

    assert policy.order["require_server_side_sl"] is True
    assert policy.order["require_server_side_tp"] is True

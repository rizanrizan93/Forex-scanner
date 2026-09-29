from pathlib import Path

from fx_scanner.demo_broker_order_smoke_v272 import (
    ENTRY_DISCOUNT_FRACTION,
    LOT,
    PROTECTION_FRACTION,
    SIGNAL_KEY,
    smoke_geometry,
)


def test_v272_smoke_geometry_is_remote_buy_limit_with_protection() -> None:
    geometry = smoke_geometry(bid=4200.0, digits=2)
    assert geometry["entry"] == 4074.0
    assert geometry["sl"] < geometry["entry"] < geometry["tp"] < 4200.0
    assert ENTRY_DISCOUNT_FRACTION == 0.03
    assert PROTECTION_FRACTION == 0.0025
    assert LOT == 0.01


def test_v272_smoke_is_separate_from_strategy_statistics() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fx_scanner/demo_broker_order_smoke_v272.py"
    ).read_text()
    assert 'event_type=EVENT_TYPE' in source
    assert '"strategy_statistics_influence": False' in source
    assert '"live_execution_authority": False' in source
    assert 'order_type=OrderType.LIMIT' in source
    assert 'session.cancel_order(order_id)' in source
    assert '"SMOKE_CANCEL_VERIFIED"' in source
    assert SIGNAL_KEY == "RIZAN_BROKER_ROUTE_SMOKE_V272"


def test_v272_execution_lane_enables_only_self_disabling_demo_smoke() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/ctrader-demo-xau-execution-lane.yml"
    ).read_text()
    assert 'CTRADER_DEMO_BROKER_SMOKE_V272_ENABLED: "1"' in workflow
    assert "One-time cTrader DEMO broker route smoke V272" in workflow
    assert "python -m fx_scanner.demo_broker_order_smoke_v272" in workflow
    assert "continue-on-error: true" in workflow

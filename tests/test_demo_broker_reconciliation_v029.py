from pathlib import Path
from types import SimpleNamespace

from fx_scanner.config import load_project_config
from fx_scanner.demo_calibration_autotrade import _safe_skip_fields
from fx_scanner.execution.demo_autotrade import CTraderDemoAutoExecutor
from fx_scanner.execution.models import ExecutionMode
from fx_scanner.execution.policy import ExecutionPolicy


class Store:
    pass


class Router:
    control_gate = None


class CapacityGateway:
    session = None

    def __init__(self, positions):
        self.positions = positions

    def position_count(self):
        return self.positions


class Session:
    account_id = 1

    def ensure_connected(self):
        return None

    def symbol_info(self, symbol):
        assert symbol == "USDCHF"
        return SimpleNamespace(symbolId=42)

    def reconcile(self):
        return SimpleNamespace(
            position=(SimpleNamespace(tradeData=SimpleNamespace(symbolId=42)),)
        )


class SymbolGateway:
    def __init__(self):
        self.session = Session()

    def position_count(self):
        return 1


def policy(max_positions=2):
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={},
        order={"max_signal_age_seconds": 300},
        live_safety={"require_control_plane": False},
        broker={"research": "CTRADER", "execution": "CTRADER"},
        ctrader={
            "role": "RESEARCH_AND_DEMO_EXECUTION",
            "environment": "DEMO",
            "require_demo": True,
        },
        demo_safety={
            "min_signal_coverage": 0.8,
            "max_order_lots": 0.01,
            "max_risk_pct": 1.0,
            "max_concurrent_positions": max_positions,
        },
    )


def executor(gateway, *, max_positions=2):
    return CTraderDemoAutoExecutor(
        cfg=load_project_config(),
        policy=policy(max_positions=max_positions),
        gateway=gateway,
        router=Router(),
        store=Store(),
    )


def test_capacity_is_blocked_before_signal_claim():
    block = executor(CapacityGateway(2))._broker_exposure_block("EURUSD")
    assert block == "BROKER_CAPACITY_FULL:2/2"


def test_same_symbol_open_position_is_blocked_before_signal_claim():
    block = executor(SymbolGateway())._broker_exposure_block("USDCHF")
    assert block == "BROKER_SYMBOL_ALREADY_OPEN:USDCHF"


def test_free_capacity_without_session_specific_reconciliation_is_allowed():
    block = executor(CapacityGateway(1))._broker_exposure_block("EURUSD")
    assert block is None


def test_manual_close_frees_capacity_on_next_reconciliation():
    gateway = CapacityGateway(2)
    demo_executor = executor(gateway)
    assert demo_executor._broker_exposure_block("EURUSD") == "BROKER_CAPACITY_FULL:2/2"

    # Simulates the user manually closing one cTrader position. The next poll
    # reads broker state again rather than trusting stale/local position state.
    gateway.positions = 1
    assert demo_executor._broker_exposure_block("EURUSD") is None


def test_runtime_reports_live_broker_capacity_and_manual_close_detection():
    source = Path("src/fx_scanner/demo_calibration_autotrade.py").read_text()
    assert "CTRADER_DEMO_BROKER_EXPOSURE" in source
    assert "open_positions_before = int(gateway.position_count())" in source
    assert "pnl_snapshot = capture_ctrader_demo_snapshot" in source
    assert "snapshot_positions_after = len(pnl_snapshot.positions)" in source
    assert "open_positions_after = int(gateway.position_count())" in source
    assert '"broker_position_source": "CTRADER_RECONCILE_ACCOUNT_WIDE"' in source
    assert '"manual_close_detection": "NEXT_POLL"' in source
    assert '"floating_pnl"' in source
    assert "free_slots" in source


def test_skip_telemetry_exposes_reason_without_exception_message():
    assert _safe_skip_fields(
        "sig-1:EXECUTION_BLOCKED:RuntimeError:secret-like-message"
    ) == ("sig-1", "EXECUTION_BLOCKED", "RuntimeError")
    assert _safe_skip_fields("sig-2:BROKER_CAPACITY_FULL:2/2") == (
        "sig-2",
        "BROKER_CAPACITY_FULL",
        "2/2",
    )
    assert _safe_skip_fields("sig-3:BROKER_NOT_ACCEPTED") == (
        "sig-3",
        "BROKER_NOT_ACCEPTED",
        None,
    )

    source = Path("src/fx_scanner/demo_calibration_autotrade.py").read_text()
    assert "CTRADER_DEMO_SKIP_DETAIL" in source

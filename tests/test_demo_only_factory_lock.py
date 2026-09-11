import pytest

from fx_scanner.exceptions import ConfigurationError
from fx_scanner.execution.factory import build_broker_gateway, build_dual_broker_stack
from fx_scanner.execution.models import ExecutionMode
from fx_scanner.execution.policy import ExecutionPolicy


def _policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        mode=ExecutionMode.AUTO,
        scheduler={},
        order={},
        live_safety={},
        broker={"research": "CTRADER", "execution": "CTRADER"},
    )


def test_factory_rejects_direct_mt5_selection_before_credentials_or_network():
    with pytest.raises(ConfigurationError, match="permanently locked"):
        build_broker_gateway(_policy(), ("EURUSD",), backend="MT5")


def test_legacy_dual_broker_builder_is_permanently_retired():
    with pytest.raises(ConfigurationError, match="retired"):
        build_dual_broker_stack(_policy(), ("EURUSD",), {"EURUSD": 0.0001})

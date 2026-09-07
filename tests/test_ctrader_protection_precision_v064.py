from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.broker_gateway import BrokerBackend, BrokerPreflight
from fx_scanner.execution.ctrader_gateway import (
    CTraderExecutionGateway,
    CTraderPreparedOrder,
    _relative_protection_distance,
)


def test_relative_protection_distance_respects_symbol_digits():
    audjpy = SimpleNamespace(digits=3)
    btcusd = SimpleNamespace(digits=2)
    eurusd = SimpleNamespace(digits=5)

    assert _relative_protection_distance(0.217953571, audjpy) == 21800
    assert _relative_protection_distance(106.082142, btcusd) == 10608000
    assert _relative_protection_distance(0.00123456, eurusd) == 123


def test_relative_protection_distance_rejects_missing_or_zero_distance():
    with pytest.raises(CollectorUnavailable, match="digits unavailable"):
        _relative_protection_distance(0.1, SimpleNamespace())
    with pytest.raises(CollectorUnavailable, match="distance is zero"):
        _relative_protection_distance(0.0001, SimpleNamespace(digits=2))


class RejectingSession:
    def send_new_order(self, request, *, client_msg_id):
        raise CollectorUnavailable(
            "cTrader API error INVALID_REQUEST: Relative stop loss has invalid precision"
        )


class TransportFailSession:
    def send_new_order(self, request, *, client_msg_id):
        raise CollectorUnavailable("cTrader request timeout after 10.0s")


def _preflight():
    request = SimpleNamespace(clientOrderId="signal-123")
    prepared = CTraderPreparedOrder(
        request=request,
        lot_size_cents=100000,
        executable_price=1.1,
        expected_margin=1.0,
    )
    return BrokerPreflight(
        BrokerBackend.CTRADER,
        True,
        "EXPECTED_MARGIN_OK",
        "ok",
        prepared,
    )


def test_explicit_ctrader_api_rejection_is_known_no_fill():
    gateway = CTraderExecutionGateway(RejectingSession())
    result = gateway.submit(_preflight())

    assert result.accepted is False
    assert result.code == "INVALID_REQUEST"
    assert "invalid precision" in result.message


def test_transport_ambiguity_still_raises_for_router_quarantine():
    gateway = CTraderExecutionGateway(TransportFailSession())
    with pytest.raises(CollectorUnavailable, match="request timeout"):
        gateway.submit(_preflight())

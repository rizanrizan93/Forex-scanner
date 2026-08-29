from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.execution.broker_gateway import BrokerBackend
from fx_scanner.execution.ctrader_gateway import CTraderExecutionGateway
from fx_scanner.execution.ctrader_session import CTraderQuote, normalize_symbol_name
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType

UTC = timezone.utc


class FakeNewOrder:
    pass


class FakeSession:
    account_id = 987654321

    def __init__(self, *, stale=False):
        self.stale = stale
        self.sent = None
        self.symbol = SimpleNamespace(
            symbolId=11,
            lotSize=10_000_000,
            minVolume=100_000,
            maxVolume=1_000_000_000,
            stepVolume=100_000,
        )

    def ensure_connected(self):
        return None

    def trader(self):
        return SimpleNamespace(balance=1_000_000_000, moneyDigits=5, accessRights=0)

    def unrealized_pnl(self):
        return SimpleNamespace(
            moneyDigits=2,
            positionUnrealizedPnL=[SimpleNamespace(netUnrealizedPnL=5_000)],
        )

    def reconcile(self):
        return SimpleNamespace(position=[SimpleNamespace(usedMargin=100_000, moneyDigits=2)])

    def symbol_info(self, symbol):
        return self.symbol

    def quote(self, symbol):
        ts = datetime.now(tz=UTC) - (timedelta(seconds=20) if self.stale else timedelta(milliseconds=50))
        return CTraderQuote(11, 1.0999, 1.1001, ts)

    def new_order_message(self):
        return FakeNewOrder()

    def expected_margin(self, symbol_id, volume_cents):
        assert symbol_id == 11
        assert volume_cents == 500_000
        return SimpleNamespace(margin=[SimpleNamespace(buyMargin=250_000, sellMargin=240_000)], moneyDigits=2)

    def send_new_order(self, request, *, client_msg_id):
        self.sent = request
        return SimpleNamespace(
            executionType=3,
            errorCode="",
            order=SimpleNamespace(orderId=42, executedVolume=500_000, executionPrice=1.10012),
        )


def intent(order_type=OrderType.MARKET):
    return OrderIntent(
        signal_id="CTR-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=order_type,
        created_at=datetime.now(tz=UTC),
        volume=0.05,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


def test_symbol_normalization_handles_ctrader_slash():
    assert normalize_symbol_name("EUR/USD") == "EURUSD"


def test_ctrader_account_snapshot_uses_equity_and_margin():
    gateway = CTraderExecutionGateway(FakeSession())
    snap = gateway.account_snapshot()
    assert snap.backend == BrokerBackend.CTRADER
    assert snap.account_id == "987654321"
    assert snap.balance == 10_000.0
    assert snap.equity == 10_050.0
    assert snap.margin_free == 9_050.0
    assert snap.trade_allowed


def test_ctrader_market_order_uses_relative_server_sl_tp():
    session = FakeSession()
    gateway = CTraderExecutionGateway(session)
    preflight = gateway.preflight(intent(), {"comment_prefix": "FXIS"})
    assert preflight.accepted
    req = preflight.request.request
    assert req.orderType == 1
    assert req.tradeSide == 1
    assert req.volume == 500_000
    assert req.clientOrderId == "CTR-1"
    assert req.relativeStopLoss == 510
    assert req.relativeTakeProfit == 990


def test_ctrader_pending_order_uses_absolute_server_sl_tp():
    session = FakeSession()
    gateway = CTraderExecutionGateway(session)
    preflight = gateway.preflight(intent(OrderType.LIMIT), {"comment_prefix": "FXIS"})
    assert preflight.accepted
    req = preflight.request.request
    assert req.orderType == 2
    assert req.limitPrice == 1.1000
    assert req.stopLoss == 1.0950
    assert req.takeProfit == 1.1100


def test_ctrader_stale_quote_fails_closed():
    gateway = CTraderExecutionGateway(FakeSession(stale=True), max_quote_age_seconds=5)
    preflight = gateway.preflight(intent(), {"comment_prefix": "FXIS"})
    assert not preflight.accepted
    assert "stale quote" in preflight.message


def test_ctrader_submit_normalizes_lots_and_order_id():
    session = FakeSession()
    gateway = CTraderExecutionGateway(session)
    preflight = gateway.preflight(intent(), {"comment_prefix": "FXIS"})
    result = gateway.submit(preflight)
    assert result.accepted
    assert result.broker_order_id == "42"
    assert result.executed_volume == 0.05
    assert result.executed_price == 1.10012

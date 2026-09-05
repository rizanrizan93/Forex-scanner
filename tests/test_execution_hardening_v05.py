from datetime import datetime, timezone
from types import SimpleNamespace
from threading import Lock, RLock

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.audit_async import AsyncOperationalAudit
from fx_scanner.execution.ctrader_research import CTraderResearchFeed
from fx_scanner.execution.models import OrderIntent, OrderSide, OrderType
from fx_scanner.execution.mt5_gateway import MT5ExecutionGateway

UTC = timezone.utc


class FakeMT5:
    SYMBOL_TRADE_EXECUTION_MARKET = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2


def gateway():
    g = MT5ExecutionGateway.__new__(MT5ExecutionGateway)
    g.mt5 = FakeMT5()
    g.connected = True
    g._io_lock = RLock()
    g.max_quote_age_seconds = 1.0
    return g


def test_mt5_market_filling_maps_symbol_bitmask_to_order_enum():
    g = gateway()
    both = SimpleNamespace(trade_exemode=2, filling_mode=3)
    fok = SimpleNamespace(trade_exemode=2, filling_mode=1)
    assert g._order_filling(both, OrderType.MARKET) == FakeMT5.ORDER_FILLING_IOC
    assert g._order_filling(fok, OrderType.MARKET) == FakeMT5.ORDER_FILLING_FOK


def test_mt5_market_filling_fails_closed_when_broker_advertises_none():
    g = gateway()
    info = SimpleNamespace(trade_exemode=2, filling_mode=0)
    with pytest.raises(CollectorUnavailable, match="NO_SUPPORTED_MARKET_FILLING"):
        g._order_filling(info, OrderType.MARKET)


def test_mt5_pending_filling_uses_return():
    g = gateway()
    info = SimpleNamespace(trade_exemode=2, filling_mode=1)
    assert g._order_filling(info, OrderType.LIMIT) == FakeMT5.ORDER_FILLING_RETURN


def _intent(entry=1.1000):
    return OrderIntent(
        signal_id="FINAL-GEOM",
        symbol="EURUSD",
        broker_symbol="EURUSDc",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        created_at=datetime.now(tz=UTC),
        volume=0.10,
        entry_price=entry,
        stop_loss=1.0950,
        take_profit=1.1100,
        risk_pct=0.25,
    )


def test_final_preflight_geometry_blocks_price_race():
    intent = _intent()
    MT5ExecutionGateway._assert_final_market_geometry(
        intent, 1.1001, max_entry_drift_r=0.03
    )
    with pytest.raises(CollectorUnavailable, match="FINAL_PRICE_DRIFT_BLOCK"):
        MT5ExecutionGateway._assert_final_market_geometry(
            intent, 1.1003, max_entry_drift_r=0.03
        )


class DummySession:
    def __init__(self):
        self.healthy = True
        self.loads = 0
        self.subscriptions = 0
    def health(self): return self.healthy
    def ensure_connected(self): self.healthy = True
    def load_symbols(self, symbols): self.loads += 1
    def subscribe_spots(self, symbols): self.subscriptions += 1
    def quote(self, symbol): return ("quote", symbol)
    def symbol_info(self, symbol):
        return SimpleNamespace(
            tradingMode=0,
            scheduleTimeZone="UTC",
            schedule=(SimpleNamespace(startSecond=0, endSecond=7 * 86400),),
            holiday=(),
            digits=5,
            pipPosition=4,
        )
    def close(self): self.closed = True


def test_ctrader_research_facade_exposes_no_order_methods():
    feed = CTraderResearchFeed(DummySession(), ["EURUSD"])
    assert feed.health() is True
    assert feed.quote("EURUSD") == ("quote", "EURUSD")
    assert not hasattr(feed, "send_new_order")
    assert not hasattr(feed, "new_order_message")
    assert not hasattr(feed, "preflight")
    assert not hasattr(feed, "submit")


class AuditStore:
    def __init__(self):
        self.events = []
    def record_order_event(self, **event):
        self.events.append(event)


def test_async_audit_graceful_stop_drains_queue():
    store = AuditStore()
    worker = AsyncOperationalAudit(store, poll_seconds=0.01)
    worker.start()
    for i in range(10):
        assert worker.emit({
            "backend": "MT5",
            "account_id": "1",
            "signal_key": f"S{i}",
            "event_type": "TEST",
        })
    worker.stop(timeout=1)
    assert len(store.events) == 10
    assert worker.health()["queued"] == 0


def test_ctrader_research_feed_restores_subscriptions_after_reconnect():
    session = DummySession()
    session.healthy = False
    feed = CTraderResearchFeed(session, ["EURUSD", "USDJPY"])
    assert feed.quote("EURUSD") == ("quote", "EURUSD")
    assert session.loads == 1
    assert session.subscriptions == 1
    # Healthy subsequent quote must not resubscribe on every read.
    feed.quote("USDJPY")
    assert session.loads == 1
    assert session.subscriptions == 1


def test_ctrader_two_sided_quote_uses_latest_price_side_timestamp():
    from fx_scanner.execution.ctrader_session import CTraderOpenApiSession

    session = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    session.symbol_id_by_name = {"EURUSD": 7}
    session._quotes_lock = Lock()
    newer = datetime(2026, 8, 30, 7, 0, 1, tzinfo=UTC)
    older = datetime(2026, 8, 30, 7, 0, 0, tzinfo=UTC)
    session._quotes_by_id = {
        7: {
            "bid": 1.1000,
            "ask": 1.1002,
            "bid_timestamp": newer,
            "ask_timestamp": older,
        }
    }
    quote = session.quote("EURUSD")
    assert quote.timestamp == newer


class AccountMT5:
    def __init__(self, *, account_allowed=True, expert=True, terminal_allowed=True, api_disabled=False):
        self.account_allowed = account_allowed
        self.expert = expert
        self.terminal_allowed = terminal_allowed
        self.api_disabled = api_disabled
    def account_info(self):
        return SimpleNamespace(
            login=123,
            balance=10000,
            equity=10000,
            margin_free=9000,
            trade_allowed=self.account_allowed,
            trade_expert=self.expert,
            currency="USC",
        )
    def terminal_info(self):
        return SimpleNamespace(
            connected=True,
            trade_allowed=self.terminal_allowed,
            tradeapi_disabled=self.api_disabled,
        )
    def last_error(self):
        return (0, "ok")


@pytest.mark.parametrize(
    "account_allowed,expert,terminal_allowed,api_disabled,expected",
    [
        (True, True, True, False, True),
        (False, True, True, False, False),
        (True, False, True, False, False),
        (True, True, False, False, False),
        (True, True, True, True, False),
    ],
)
def test_mt5_account_snapshot_requires_all_automation_permissions(
    account_allowed, expert, terminal_allowed, api_disabled, expected
):
    g = MT5ExecutionGateway.__new__(MT5ExecutionGateway)
    g.mt5 = AccountMT5(
        account_allowed=account_allowed,
        expert=expert,
        terminal_allowed=terminal_allowed,
        api_disabled=api_disabled,
    )
    g.connected = True
    g._io_lock = RLock()
    snapshot = g.account_snapshot()
    assert snapshot.trade_allowed is expected


def test_ctrader_missing_server_timestamp_is_rejected():
    from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
    with pytest.raises(CollectorUnavailable, match="timestamp unavailable"):
        CTraderOpenApiSession._event_ts(None)

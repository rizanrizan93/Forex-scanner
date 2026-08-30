from datetime import datetime, timezone
from types import SimpleNamespace
from threading import RLock

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
    def health(self): return True
    def ensure_connected(self): return None
    def quote(self, symbol): return ("quote", symbol)
    def symbol_info(self, symbol): return ("info", symbol)
    def close(self): self.closed = True


def test_ctrader_research_facade_exposes_no_order_methods():
    feed = CTraderResearchFeed(DummySession())
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

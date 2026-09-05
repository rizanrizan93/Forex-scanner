from datetime import datetime, timedelta, timezone
from threading import Lock
from types import SimpleNamespace

from fx_scanner.config import load_project_config
from fx_scanner.execution.ctrader_research import CTraderResearchFeed
from fx_scanner.execution.ctrader_session import CTraderOpenApiSession
from fx_scanner.signal_producer import CTraderSignalProducer
from fx_scanner.storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
NOW = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


class Msg:
    def __init__(self):
        self.ctidTraderAccountId = 0
        self.symbolId = []
        self.subscribeToSpotTimestamp = False


def test_session_refresh_spot_snapshot_unsubscribes_clears_and_resubscribes():
    session = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    session.account_id = 123
    session.symbol_id_by_name = {"EURCHF": 77}
    session._quotes_lock = Lock()
    session._quotes_by_id = {
        77: {
            "bid": 1.1,
            "ask": 1.2,
            "bid_timestamp": NOW,
            "ask_timestamp": NOW,
        }
    }
    session.msg = {
        "UnsubscribeSpotsReq": Msg,
        "SubscribeSpotsReq": Msg,
    }
    session.ensure_connected = lambda: None
    sent = []

    def send(message, *, client_msg_id=None, timeout=None):
        del timeout
        sent.append((client_msg_id, message, 77 in session._quotes_by_id))
        return object()

    session._send_sync = send

    session.refresh_spot_snapshot("EURCHF")

    assert len(sent) == 2
    assert sent[0][0].startswith("unspots-")
    assert sent[0][1].ctidTraderAccountId == 123
    assert sent[0][1].symbolId == [77]
    assert sent[0][2] is True
    assert sent[1][0].startswith("spots-refresh-")
    assert sent[1][1].ctidTraderAccountId == 123
    assert sent[1][1].symbolId == [77]
    assert sent[1][1].subscribeToSpotTimestamp is True
    assert sent[1][2] is False
    assert 77 not in session._quotes_by_id


class SessionFacade:
    def __init__(self):
        self.refreshes = []

    def health(self):
        return True

    def ensure_connected(self):
        return None

    def symbol_info(self, _symbol):
        return SimpleNamespace(
            tradingMode=0,
            scheduleTimeZone="UTC",
            schedule=(SimpleNamespace(startSecond=0, endSecond=7 * 86400),),
            holiday=(),
            digits=5,
            pipPosition=4,
        )

    def refresh_spot_snapshot(self, symbol):
        self.refreshes.append(symbol)

    def close(self):
        return None


def test_research_feed_exposes_read_only_snapshot_refresh():
    session = SessionFacade()
    feed = CTraderResearchFeed(session, ["EURCHF"])
    feed.refresh_quote_snapshot("EURCHF")
    assert session.refreshes == ["EURCHF"]


class Quote:
    def __init__(self, age):
        self.bid = 1.1000
        self.ask = 1.1002
        self.timestamp = NOW - timedelta(seconds=age)


class SnapshotFeed:
    def __init__(self):
        self.refreshes = 0
        self.quote_calls = 0

    def quote(self, _symbol):
        self.quote_calls += 1
        return Quote(5.0 if self.refreshes == 0 else 0.2)

    def refresh_quote_snapshot(self, _symbol):
        self.refreshes += 1


class Store:
    pass


def test_producer_refreshes_stale_quote_once_without_relaxing_two_second_gate():
    cfg = load_project_config()
    feed = SnapshotFeed()
    producer = CTraderSignalProducer(
        cfg,
        feed,
        Store(),
        code_version="test",
        max_quote_age_seconds=2.0,
        quote_wait_timeout_seconds=0.5,
        quote_poll_seconds=0.1,
        sleeper=lambda _seconds: None,
        clock=lambda: NOW,
    )

    quote, error = producer._fresh_quote("EURCHF")

    assert error is None
    assert quote is not None
    assert feed.refreshes == 1
    assert feed.quote_calls == 2
    assert (NOW - quote.timestamp).total_seconds() <= 2.0

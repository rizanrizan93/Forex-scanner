from datetime import datetime, timedelta, timezone

from fx_scanner.execution.ctrader_session import CTraderOpenApiSession

UTC = timezone.utc


def _session_with_quote_state(*, bid_age: float, ask_age: float):
    now = datetime.now(tz=UTC)
    session = CTraderOpenApiSession.__new__(CTraderOpenApiSession)
    session.symbol_id_by_name = {"EURUSD": 1}
    from threading import Lock
    session._quotes_lock = Lock()
    session._quotes_by_id = {
        1: {
            "bid": 1.1000,
            "ask": 1.1002,
            "bid_timestamp": now - timedelta(seconds=bid_age),
            "ask_timestamp": now - timedelta(seconds=ask_age),
        }
    }
    return session


def test_quote_freshness_uses_latest_optional_price_side_event():
    session = _session_with_quote_state(bid_age=8.0, ask_age=0.2)
    quote = session.quote("EURUSD")
    age = (datetime.now(tz=UTC) - quote.timestamp).total_seconds()
    assert age < 1.0


def test_quote_freshness_tracks_new_bid_when_ask_unchanged():
    session = _session_with_quote_state(bid_age=0.2, ask_age=8.0)
    quote = session.quote("EURUSD")
    age = (datetime.now(tz=UTC) - quote.timestamp).total_seconds()
    assert age < 1.0

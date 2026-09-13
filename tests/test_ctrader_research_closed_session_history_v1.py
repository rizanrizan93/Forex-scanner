from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.exceptions import CollectorUnavailable
from fx_scanner.execution.ctrader_research import CTraderResearchFeed

UTC = timezone.utc


class ClosedSession:
    def __init__(self):
        self.history_calls = []
        self.quote_calls = 0

    def health(self):
        return True

    def ensure_connected(self):
        return None

    def symbol_info(self, symbol):
        return SimpleNamespace(
            tradingMode=0,
            scheduleTimeZone="UTC",
            schedule=(SimpleNamespace(startSecond=0, endSecond=5 * 86400),),
            holiday=(),
            digits=5,
            pipPosition=4,
        )

    def quote(self, symbol):
        self.quote_calls += 1
        raise CollectorUnavailable(f"cTrader quote incomplete for {symbol}")

    def historical_bars(
        self,
        symbol,
        timeframe,
        *,
        from_time,
        to_time,
        count,
        spread_proxy,
    ):
        self.history_calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "from_time": from_time,
                "to_time": to_time,
                "count": count,
                "spread_proxy": spread_proxy,
            }
        )
        return ("READ_ONLY_HISTORY_OK",)

    def close(self):
        return None


def test_historical_bars_allowed_when_broker_session_closed_but_quote_remains_blocked():
    session = ClosedSession()
    feed = CTraderResearchFeed(session, ("XAUUSD",))
    saturday = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(
        CollectorUnavailable,
        match="CTRADER_MARKET_CLOSED:XAUUSD:OUTSIDE_BROKER_SESSION",
    ):
        feed.quote("XAUUSD", at=saturday)

    result = feed.historical_bars(
        "XAUUSD",
        "D1",
        from_time=saturday - timedelta(days=400),
        to_time=saturday,
        count=232,
    )

    assert result == ("READ_ONLY_HISTORY_OK",)
    assert len(session.history_calls) == 1
    call = session.history_calls[0]
    assert call["symbol"] == "XAUUSD"
    assert call["timeframe"] == "D1"
    assert call["count"] == 232
    assert call["spread_proxy"] == 0.0
    assert session.quote_calls == 1


def test_closed_session_history_never_calls_market_status_gate():
    session = ClosedSession()
    feed = CTraderResearchFeed(session, ("USDJPY",))
    saturday = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)

    result = feed.historical_bars(
        "USDJPY",
        "H4",
        from_time=saturday - timedelta(days=100),
        to_time=saturday,
        count=232,
    )

    assert result == ("READ_ONLY_HISTORY_OK",)
    assert session.history_calls[0]["spread_proxy"] == 0.0

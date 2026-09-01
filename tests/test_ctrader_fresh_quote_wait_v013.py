from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.execution.ctrader_gateway import CTraderExecutionGateway
from fx_scanner.exceptions import CollectorUnavailable

UTC = timezone.utc


class SequencedSession:
    def __init__(self, ages):
        self.ages = list(ages)
        self.calls = 0

    def quote(self, symbol):
        age = self.ages[min(self.calls, len(self.ages) - 1)]
        self.calls += 1
        return SimpleNamespace(
            bid=1.0999,
            ask=1.1000,
            timestamp=datetime.now(tz=UTC) - timedelta(seconds=age),
        )


def test_market_quote_waits_for_new_tick_without_relaxing_freshness():
    session = SequencedSession([4.0, 3.0, 0.2])
    gateway = CTraderExecutionGateway(
        session,
        max_quote_age_seconds=2.0,
        quote_wait_timeout_seconds=1.0,
        quote_poll_seconds=0.01,
    )
    quote = gateway.market_quote("EURUSD")
    assert quote.ask == 1.1000
    assert session.calls == 3


def test_market_quote_fails_if_no_fresh_tick_arrives():
    session = SequencedSession([4.0])
    gateway = CTraderExecutionGateway(
        session,
        max_quote_age_seconds=2.0,
        quote_wait_timeout_seconds=0.03,
        quote_poll_seconds=0.01,
    )
    with pytest.raises(CollectorUnavailable, match="stale quote after bounded wait"):
        gateway.market_quote("EURUSD")
    assert session.calls >= 2


def test_market_quote_rejects_future_timestamp_immediately():
    session = SequencedSession([-2.0])
    gateway = CTraderExecutionGateway(
        session,
        max_quote_age_seconds=2.0,
        quote_wait_timeout_seconds=1.0,
        quote_poll_seconds=0.01,
    )
    with pytest.raises(CollectorUnavailable, match="timestamp is in the future"):
        gateway.market_quote("EURUSD")
    assert session.calls == 1

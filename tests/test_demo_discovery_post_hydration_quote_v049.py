from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fx_scanner.demo_signal_producer import ExplicitDemoTechnicalSignalProducer
from fx_scanner.models import Bar

UTC = timezone.utc


class Feed:
    def __init__(self, now: datetime, *, refresh_becomes_fresh: bool):
        self.now = now
        self.refresh_becomes_fresh = refresh_becomes_fresh
        self.refreshed = False
        self.refresh_calls = 0
        self.history_calls = 0

    def quote(self, _symbol):
        age = 0.2 if self.refreshed and self.refresh_becomes_fresh else 30.0
        return SimpleNamespace(
            bid=1.1000,
            ask=1.1002,
            timestamp=self.now - timedelta(seconds=age),
        )

    def refresh_quote_snapshot(self, _symbol):
        # The fix must defer freshness refresh until all fast history is hydrated.
        assert self.history_calls >= 3
        self.refresh_calls += 1
        self.refreshed = True

    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        self.history_calls += 1
        seconds = {"M5": 300, "M15": 900, "H1": 3600}[timeframe]
        bars = []
        for index in range(int(count)):
            timestamp = self.now - timedelta(seconds=seconds * (index + 2))
            bars.append(
                Bar(
                    symbol,
                    timeframe,
                    timestamp,
                    1.1000,
                    1.1010,
                    1.0990,
                    1.1005,
                    100,
                    0.0002,
                    0.0002,
                )
            )
        return tuple(reversed(bars))


class DummyStore:
    pass


def cfg():
    pair = SimpleNamespace(symbol="EURUSD")
    return SimpleNamespace(
        pairs=(pair,),
        pair_map={"EURUSD": pair},
        timeframes={"M5": 300, "M15": 900, "H1": 3600},
        strategy={
            "mtf": {
                "required_timeframes": ("M5", "M15", "H1"),
                "minimum_bars": {"M5": 2, "M15": 2, "H1": 2},
            }
        },
    )


def producer(feed: Feed, now: datetime):
    return ExplicitDemoTechnicalSignalProducer(
        cfg(),
        feed,
        DummyStore(),
        code_version="TEST",
        historical_request_delay_seconds=0.20,
        max_quote_age_seconds=2.0,
        quote_wait_timeout_seconds=0.02,
        quote_poll_seconds=0.01,
        sleeper=lambda _seconds: None,
        clock=lambda: now,
        technical_only_scalping=True,
    )


def test_discovery_hydrates_history_before_refreshing_stale_quote():
    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    feed = Feed(now, refresh_becomes_fresh=True)

    market, failures = producer(feed, now)._fetch_fast_market(as_of=now)

    assert failures == {}
    assert tuple(market) == ("EURUSD",)
    assert feed.history_calls == 3
    assert feed.refresh_calls == 1


def test_discovery_still_fails_closed_if_post_hydration_quote_is_stale():
    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    feed = Feed(now, refresh_becomes_fresh=False)

    market, failures = producer(feed, now)._fetch_fast_market(as_of=now)

    assert market == {}
    assert "EURUSD" in failures
    assert failures["EURUSD"].startswith("QUOTE_STALE:")
    # Retry remains bounded and never converts stale evidence into valid evidence.
    assert feed.refresh_calls >= 1

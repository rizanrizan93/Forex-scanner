import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.models import Bar
from fx_scanner.producer_guards import ProductionGuardResolver
from fx_scanner.providers.news import ForexFactoryCalendarProvider
from fx_scanner.ranking import PairRank

UTC = timezone.utc
NOW = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


class Response:
    def __init__(self, body):
        self.status_code = 200
        self.body = body
        self.headers = {}
        self.final_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class CalendarTransport:
    def __init__(self, events):
        self.events = events

    def get(self, url, *, allowed_host, headers=None):
        assert url.startswith("https://")
        assert allowed_host == "nfs.faireconomy.media"
        assert headers["Accept"] == "application/json"
        return Response(json.dumps(self.events).encode("utf-8"))


def event(when, *, impact="Low", currency="USD", title="Current event"):
    return {
        "title": title,
        "country": currency,
        "date": when.isoformat(),
        "impact": impact,
        "forecast": "",
        "previous": "",
    }


def rank(symbol, direction, number):
    return PairRank(
        symbol=symbol,
        direction=direction,
        relative_macro_edge=50.0,
        relative_technical_edge=40.0,
        cross_asset_edge=30.0,
        pair_edge=60.0,
        absolute_edge=60.0,
        coverage=1.0,
        missing_components=(),
        rank=number,
    )


def bundle(symbol):
    cfg = load_project_config()
    out = {}
    counts = cfg.strategy["mtf"]["minimum_bars"]
    for tf in cfg.strategy["mtf"]["required_timeframes"]:
        seconds = cfg.timeframes[tf]
        count = int(counts[tf]) + 5
        start = NOW - timedelta(seconds=seconds * (count + 1))
        bars = []
        for i in range(count):
            ts = start + timedelta(seconds=seconds * i)
            base = 1.0 + i * 0.0001
            bars.append(
                Bar(
                    symbol,
                    tf,
                    ts,
                    base,
                    base + 0.0003,
                    base - 0.0003,
                    base + 0.0001,
                    100 + i,
                    0.0002,
                    0.0002,
                )
            )
        out[tf] = tuple(bars)
    return out


class Feed:
    def __init__(self, *, age_seconds=0.0):
        self.age_seconds = age_seconds

    def quote(self, _symbol):
        return SimpleNamespace(
            bid=1.1000,
            ask=1.1002,
            timestamp=NOW - timedelta(seconds=self.age_seconds),
        )


def calendar_provider(events):
    return ForexFactoryCalendarProvider(CalendarTransport(events))


def test_forex_factory_calendar_rejects_stale_week():
    provider = calendar_provider([event(NOW - timedelta(days=10))])
    with pytest.raises(Exception, match="current runtime week"):
        provider.fetch(now=NOW)


def test_guard_resolver_populates_all_external_guards_when_evidence_exists():
    cfg = load_project_config()
    resolver = ProductionGuardResolver(
        cfg,
        Feed(),
        calendar_provider=calendar_provider([event(NOW)]),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
    )
    candidate = rank("EURUSD", "LONG", 1)
    result = resolver.resolve(
        candidates=[candidate],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )
    flags = result.flags_by_symbol["EURUSD"]
    assert set(flags) == set(ProductionGuardResolver.EXTERNAL_GUARDS)
    assert flags["NEWS_BLOCK"] is False
    assert flags["SPREAD_BLOCK"] is False
    assert flags["VOLATILITY_BLOCK"] is False
    assert flags["CORRELATION_BLOCK"] is False
    assert flags["RISK_BLOCK"] is False
    assert flags["DATA_QUALITY_BLOCK"] is False
    assert result.missing_by_symbol["EURUSD"] == ()


def test_high_impact_event_blocks_relevant_pair():
    cfg = load_project_config()
    provider = calendar_provider(
        [event(NOW + timedelta(minutes=10), impact="High", currency="EUR", title="ECB")]
    )
    resolver = ProductionGuardResolver(
        cfg,
        Feed(),
        calendar_provider=provider,
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
    )
    result = resolver.resolve(
        candidates=[rank("EURUSD", "LONG", 1)],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )
    assert result.flags_by_symbol["EURUSD"]["NEWS_BLOCK"] is True


class BrokenCalendar:
    def fetch(self, *, now):
        raise RuntimeError("calendar unavailable")


def test_calendar_failure_leaves_news_guard_missing_not_false():
    cfg = load_project_config()
    resolver = ProductionGuardResolver(
        cfg,
        Feed(),
        calendar_provider=BrokenCalendar(),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
    )
    result = resolver.resolve(
        candidates=[rank("EURUSD", "LONG", 1)],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )
    flags = result.flags_by_symbol["EURUSD"]
    assert "NEWS_BLOCK" not in flags
    assert "NEWS_BLOCK" in result.missing_by_symbol["EURUSD"]
    assert result.calendar_error.startswith("RuntimeError:")


def test_stale_quote_never_becomes_spread_clear():
    cfg = load_project_config()
    resolver = ProductionGuardResolver(
        cfg,
        Feed(age_seconds=10),
        calendar_provider=calendar_provider([event(NOW)]),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
    )
    result = resolver.resolve(
        candidates=[rank("EURUSD", "LONG", 1)],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )
    flags = result.flags_by_symbol["EURUSD"]
    assert "SPREAD_BLOCK" not in flags
    assert flags["DATA_QUALITY_BLOCK"] is True
    assert "SPREAD_BLOCK" in result.missing_by_symbol["EURUSD"]


def test_directional_correlation_blocks_lower_ranked_duplicate_exposure():
    cfg = load_project_config()
    resolver = ProductionGuardResolver(
        cfg,
        Feed(),
        calendar_provider=calendar_provider([event(NOW)]),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
    )
    first = rank("EURUSD", "LONG", 1)
    second = rank("GBPUSD", "LONG", 2)
    result = resolver.resolve(
        candidates=[first, second],
        bars_by_symbol={
            "EURUSD": bundle("EURUSD"),
            "GBPUSD": bundle("GBPUSD"),
        },
        as_of=NOW,
    )
    assert result.flags_by_symbol["EURUSD"]["CORRELATION_BLOCK"] is False
    assert result.flags_by_symbol["GBPUSD"]["CORRELATION_BLOCK"] is True



class SequencedGuardFeed:
    def __init__(self, ages):
        self.ages = list(ages)
        self.calls = 0

    def quote(self, _symbol):
        age = self.ages[min(self.calls, len(self.ages) - 1)]
        self.calls += 1
        return SimpleNamespace(
            bid=1.1000,
            ask=1.1002,
            timestamp=NOW - timedelta(seconds=age),
        )


def test_guard_waits_boundedly_for_fresh_quote_without_relaxing_freshness():
    cfg = load_project_config()
    feed = SequencedGuardFeed([5.0, 3.0, 0.2])
    sleeps = []
    resolver = ProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=calendar_provider([event(NOW)]),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
        quote_wait_timeout_seconds=0.5,
        quote_poll_seconds=0.1,
        sleeper=sleeps.append,
        clock=lambda: NOW,
    )
    result = resolver.resolve(
        candidates=[rank("EURUSD", "LONG", 1)],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )

    flags = result.flags_by_symbol["EURUSD"]
    assert feed.calls == 3
    assert sleeps == [0.1, 0.1]
    assert flags["SPREAD_BLOCK"] is False
    assert flags["DATA_QUALITY_BLOCK"] is False
    assert result.missing_by_symbol["EURUSD"] == ()


def test_guard_bounded_wait_still_fails_closed_when_quote_remains_stale():
    cfg = load_project_config()
    feed = SequencedGuardFeed([5.0])
    resolver = ProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=calendar_provider([event(NOW)]),
        max_quote_age_seconds=2.0,
        max_spread_pips=4.0,
        demo_max_risk_pct=0.25,
        quote_wait_timeout_seconds=0.2,
        quote_poll_seconds=0.1,
        sleeper=lambda _seconds: None,
        clock=lambda: NOW,
    )
    result = resolver.resolve(
        candidates=[rank("EURUSD", "LONG", 1)],
        bars_by_symbol={"EURUSD": bundle("EURUSD")},
        as_of=NOW,
    )

    assert feed.calls == 3
    assert "SPREAD_BLOCK" in result.missing_by_symbol["EURUSD"]
    assert result.flags_by_symbol["EURUSD"]["DATA_QUALITY_BLOCK"] is True

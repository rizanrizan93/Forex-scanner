from datetime import datetime, timedelta, timezone

from fx_scanner.config import load_project_config
from fx_scanner.demo_five_core_candidate_producer import (
    FIVE_CORE_SYMBOLS,
    _subset_cfg,
    _with_history_requirements,
)
from fx_scanner.demo_five_core_history_probe import probe_history
from fx_scanner.models import Bar

UTC = timezone.utc


class FakeHistoryOnlyFeed:
    def __init__(self, as_of: datetime):
        self.as_of = as_of
        self.calls = []

    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        self.calls.append((symbol, timeframe, from_time, to_time, count))
        seconds = 86400 if timeframe == "D1" else 14400
        first = self.as_of - timedelta(seconds=seconds * (count + 2))
        return tuple(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=first + timedelta(seconds=seconds * i),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                tick_count=100,
                spread_avg=0.1,
                spread_max=0.2,
            )
            for i in range(count)
        )


def test_history_probe_needs_no_live_quote_and_checks_all_five_core_pairs():
    as_of = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
    cfg = _with_history_requirements(
        _subset_cfg(load_project_config(None), FIVE_CORE_SYMBOLS)
    )
    feed = FakeHistoryOnlyFeed(as_of)

    counts, failures = probe_history(
        feed,
        cfg,
        as_of=as_of,
        sleeper=lambda _: None,
    )

    assert failures == {}
    assert set(counts) == set(FIVE_CORE_SYMBOLS)
    assert len(feed.calls) == len(FIVE_CORE_SYMBOLS) * 2
    for symbol in FIVE_CORE_SYMBOLS:
        assert counts[symbol]["D1"] >= 220
        assert counts[symbol]["H4"] >= 220

    # The fake intentionally has no quote() method: successful completion proves
    # the readiness probe is independent of live broker-session quotes.
    for _, timeframe, from_time, to_time, count in feed.calls:
        assert timeframe in {"D1", "H4"}
        assert count == 232
        assert from_time < to_time == as_of

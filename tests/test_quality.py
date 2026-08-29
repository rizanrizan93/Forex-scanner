from datetime import datetime, timedelta, timezone

from fx_scanner.models import Tick
from fx_scanner.quality import assess_ticks


UTC = timezone.utc


def test_fresh_feed_passes():
    now = datetime(2026, 8, 29, 12, 0, 10, tzinfo=UTC)
    ticks = [
        Tick("EURUSD", now - timedelta(seconds=10-i), 1.1, 1.1001)
        for i in range(5)
    ]
    report = assess_ticks(ticks, now=now)
    assert report.valid
    assert "STALE_FEED" not in report.issues


def test_stale_feed_blocks():
    now = datetime(2026, 8, 29, 12, 1, tzinfo=UTC)
    ticks = [Tick("EURUSD", now - timedelta(minutes=2), 1.1, 1.1001)]
    report = assess_ticks(ticks, now=now)
    assert not report.valid
    assert "STALE_FEED" in report.issues


def test_non_monotonic_blocks():
    base = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    ticks = [
        Tick("EURUSD", base + timedelta(seconds=2), 1.1, 1.1001),
        Tick("EURUSD", base + timedelta(seconds=1), 1.1, 1.1001),
    ]
    report = assess_ticks(ticks, now=base + timedelta(seconds=2))
    assert not report.valid
    assert "NON_MONOTONIC_TIME" in report.issues

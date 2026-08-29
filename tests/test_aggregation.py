from datetime import datetime, timedelta, timezone

from fx_scanner.aggregation import aggregate_ticks
from fx_scanner.models import Tick


UTC = timezone.utc


def test_m1_aggregation_is_deterministic():
    start = datetime(2026, 8, 29, 12, 0, 1, tzinfo=UTC)
    ticks = [
        Tick("EURUSD", start + timedelta(seconds=i * 10), 1.1000 + i * 0.0001, 1.1002 + i * 0.0001)
        for i in range(7)
    ]
    bars = aggregate_ticks(ticks, "M1", 60)
    assert len(bars) == 2
    assert bars[0].timestamp == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    assert bars[0].tick_count == 6
    assert bars[1].tick_count == 1
    assert bars[0].high >= bars[0].low

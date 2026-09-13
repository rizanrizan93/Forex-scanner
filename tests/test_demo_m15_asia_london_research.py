from datetime import date, datetime, timezone

from fx_scanner.demo_m15_asia_london_research import fetch_monthly_history
from fx_scanner.models import Bar

UTC = timezone.utc


def _bar(ts: datetime) -> Bar:
    return Bar(
        symbol="AUDUSD",
        timeframe="M15",
        timestamp=ts,
        open=0.66,
        high=0.661,
        low=0.659,
        close=0.6605,
        tick_count=1,
        spread_avg=0.0,
        spread_max=0.0,
    )


class PaddingFeed:
    def historical_bars(self, symbol, timeframe, *, from_time, to_time, count):
        assert symbol == "AUDUSD"
        assert timeframe == "M15"
        assert count > 0
        return (
            _bar(datetime(2023, 12, 7, 13, 0, tzinfo=UTC)),
            _bar(datetime(2024, 1, 2, 0, 0, tzinfo=UTC)),
            _bar(datetime(2024, 2, 2, 0, 0, tzinfo=UTC)),
        )


def test_fetch_monthly_history_discards_transport_padding_outside_window():
    rows = fetch_monthly_history(
        PaddingFeed(),
        "AUDUSD",
        start_month=date(2024, 1, 1),
        end_month=date(2024, 1, 1),
        sleeper=lambda _seconds: None,
    )

    assert [row.timestamp for row in rows] == [
        datetime(2024, 1, 2, 0, 0, tzinfo=UTC)
    ]

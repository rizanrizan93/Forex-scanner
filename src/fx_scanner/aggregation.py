from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .exceptions import DataContractError
from .models import Bar, Tick


UTC = timezone.utc


def floor_time(ts: datetime, seconds: int) -> datetime:
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    epoch = int(ts.astimezone(UTC).timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC)


def aggregate_ticks(ticks: list[Tick], timeframe: str, seconds: int) -> list[Bar]:
    if not ticks:
        return []
    symbols = {t.symbol for t in ticks}
    if len(symbols) != 1:
        raise DataContractError("aggregate_ticks accepts exactly one symbol per call")

    ordered = sorted(ticks, key=lambda t: t.timestamp)
    buckets: dict[datetime, list[Tick]] = defaultdict(list)
    for tick in ordered:
        buckets[floor_time(tick.timestamp, seconds)].append(tick)

    bars: list[Bar] = []
    symbol = ordered[0].symbol
    for bucket_ts in sorted(buckets):
        group = buckets[bucket_ts]
        mids = [t.mid for t in group]
        spreads = [t.spread for t in group]
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=bucket_ts,
                open=mids[0],
                high=max(mids),
                low=min(mids),
                close=mids[-1],
                tick_count=len(group),
                spread_avg=sum(spreads) / len(spreads),
                spread_max=max(spreads),
            )
        )
    return bars

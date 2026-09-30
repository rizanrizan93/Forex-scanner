from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .exceptions import CollectorUnavailable
from .models import ensure_utc

SYMBOL = "XAUUSD"
TIMEFRAME = "H1"
SECONDS = 3600
PAGE_BARS = 5_000


def fetch_h1_history(feed, *, target: int, as_of: datetime, max_pages: int = 24):
    merged = {}
    cursor = as_of
    pages: list[dict[str, Any]] = []
    previous_earliest = None
    source_exhausted = False
    for page in range(1, max_pages + 1):
        remaining = target - len(merged)
        if remaining <= 0:
            break
        count = min(PAGE_BARS, remaining)
        try:
            fetched = tuple(
                feed.historical_bars(
                    SYMBOL,
                    TIMEFRAME,
                    from_time=cursor - timedelta(seconds=count * SECONDS * 3),
                    to_time=cursor,
                    count=count,
                )
            )
        except CollectorUnavailable:
            source_exhausted = True
            pages.append({
                "page": page,
                "requested": count,
                "received": 0,
                "merged_total": len(merged),
                "terminal": "COLLECTOR_UNAVAILABLE_AT_OLDER_HISTORY",
            })
            break
        if not fetched:
            source_exhausted = True
            break
        for row in fetched:
            merged[row.timestamp] = row
        earliest = min(row.timestamp for row in fetched)
        latest = max(row.timestamp for row in fetched)
        pages.append({
            "page": page,
            "requested": count,
            "received": len(fetched),
            "merged_total": len(merged),
            "earliest": earliest.isoformat(),
            "latest": latest.isoformat(),
        })
        if previous_earliest is not None and earliest >= previous_earliest:
            source_exhausted = True
            break
        previous_earliest = earliest
        cursor = earliest - timedelta(seconds=1)

    rows = tuple(sorted(merged.values(), key=lambda row: row.timestamp))
    closed = tuple(
        row for row in rows
        if ensure_utc(row.timestamp) + timedelta(seconds=SECONDS) <= as_of
    )
    if len(closed) > target:
        closed = closed[-target:]
    return closed, pages, source_exhausted

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

from .models import Bar, Tick, ensure_utc


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class QualityReport:
    valid: bool
    record_count: int
    duplicate_count: int
    non_monotonic_count: int
    crossed_quote_count: int
    stale: bool
    spread_ratio: float | None
    issues: tuple[str, ...]


def assess_ticks(
    ticks: list[Tick],
    *,
    now: datetime | None = None,
    max_staleness: timedelta = timedelta(seconds=30),
    spread_ratio_block: float = 1.75,
) -> QualityReport:
    issues: list[str] = []
    if not ticks:
        return QualityReport(False, 0, 0, 0, 0, True, None, ("NO_DATA",))

    now_utc = ensure_utc(now or datetime.now(tz=UTC))
    duplicate_count = 0
    non_monotonic = 0
    crossed = 0
    seen: set[tuple[datetime, float, float]] = set()

    previous = None
    spreads: list[float] = []
    for tick in ticks:
        key = (tick.timestamp, tick.bid, tick.ask)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        if previous is not None and tick.timestamp < previous:
            non_monotonic += 1
        previous = tick.timestamp
        if tick.ask < tick.bid:
            crossed += 1
        spreads.append(tick.spread)

    latest = max(t.timestamp for t in ticks)
    stale = now_utc - latest > max_staleness
    med = median(spreads)
    current = spreads[-1]
    spread_ratio = None if med == 0 else current / med

    if duplicate_count:
        issues.append("DUPLICATE_TICKS")
    if non_monotonic:
        issues.append("NON_MONOTONIC_TIME")
    if crossed:
        issues.append("CROSSED_QUOTES")
    if stale:
        issues.append("STALE_FEED")
    if spread_ratio is not None and spread_ratio > spread_ratio_block:
        issues.append("SPREAD_BLOCK")

    hard_invalid = crossed > 0 or non_monotonic > 0 or stale
    return QualityReport(
        valid=not hard_invalid,
        record_count=len(ticks),
        duplicate_count=duplicate_count,
        non_monotonic_count=non_monotonic,
        crossed_quote_count=crossed,
        stale=stale,
        spread_ratio=spread_ratio,
        issues=tuple(issues),
    )


def find_bar_gaps(bars: list[Bar], seconds: int) -> list[tuple[datetime, datetime]]:
    if len(bars) < 2:
        return []
    ordered = sorted(bars, key=lambda b: b.timestamp)
    gaps: list[tuple[datetime, datetime]] = []
    expected = timedelta(seconds=seconds)
    for left, right in zip(ordered, ordered[1:]):
        if right.timestamp - left.timestamp > expected:
            # Weekend gaps are expected in spot FX and should be handled by the calendar layer.
            if left.timestamp.weekday() == 4 and right.timestamp.weekday() in (6, 0):
                continue
            gaps.append((left.timestamp, right.timestamp))
    return gaps

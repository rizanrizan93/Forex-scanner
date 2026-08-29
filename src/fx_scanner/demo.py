from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import sin

from .models import Tick, ensure_utc


UTC = timezone.utc


def generate_demo_ticks(
    symbol: str,
    start: datetime,
    *,
    minutes: int = 10,
    ticks_per_minute: int = 12,
    mid_start: float = 1.10000,
    spread: float = 0.00010,
) -> list[Tick]:
    start = ensure_utc(start)
    if minutes <= 0 or ticks_per_minute <= 0:
        raise ValueError("minutes and ticks_per_minute must be positive")
    step = timedelta(seconds=60 / ticks_per_minute)
    count = minutes * ticks_per_minute
    ticks: list[Tick] = []
    for i in range(count):
        mid = mid_start + (i * 0.000001) + sin(i / 7.0) * 0.00002
        half = spread / 2
        ticks.append(Tick(symbol, start + i * step, mid - half, mid + half))
    return ticks

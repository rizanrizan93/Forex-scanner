from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .runtime import ScheduledJob


UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class SchedulerIntervals:
    heavy_scan: timedelta
    fast_setup: timedelta
    execution_watch: timedelta
    position_monitor: timedelta

    @classmethod
    def from_seconds(cls, values: dict[str, int]) -> "SchedulerIntervals":
        return cls(
            heavy_scan=timedelta(seconds=values["heavy_scan_seconds"]),
            fast_setup=timedelta(seconds=values["fast_setup_seconds"]),
            execution_watch=timedelta(seconds=values["execution_watch_seconds"]),
            position_monitor=timedelta(seconds=values["position_monitor_seconds"]),
        )


def due(last_run: datetime | None, now: datetime, interval: timedelta) -> bool:
    now = now.astimezone(UTC)
    if last_run is None:
        return True
    return now - last_run.astimezone(UTC) >= interval


def build_runtime_job(name: str, interval_seconds: int, max_lag_seconds: int, handler) -> ScheduledJob:
    return ScheduledJob(
        name=name,
        interval_seconds=float(interval_seconds),
        max_lag_seconds=float(max_lag_seconds),
        handler=handler,
    )

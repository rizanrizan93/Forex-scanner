from __future__ import annotations

from enum import StrEnum
from threading import Lock
from time import monotonic
from typing import Mapping


class ExecutionWatchState(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    SETUP_FORMING = "SETUP_FORMING"
    ARMED = "ARMED"
    EXECUTION_READY = "EXECUTION_READY"
    MISSED = "MISSED"
    INVALIDATED = "INVALIDATED"
    COOLDOWN = "COOLDOWN"


class AdaptiveExecutionCadence:
    """Throttle expensive execution-side checks while keeping ARMED fast."""

    def __init__(self, intervals: Mapping[str, float], *, clock=monotonic):
        self.intervals = {str(k).upper(): float(v) for k, v in intervals.items()}
        if not self.intervals or any(v <= 0 for v in self.intervals.values()):
            raise ValueError("adaptive cadence intervals must be positive")
        self.clock = clock
        self._last: dict[str, float] = {}
        self._lock = Lock()

    def interval_for(self, state: str | ExecutionWatchState) -> float:
        key = str(state).upper()
        try:
            return self.intervals[key]
        except KeyError:
            return self.intervals.get("WATCH", 2.0)

    def due(self, key: str, state: str | ExecutionWatchState, *, now_mono: float | None = None) -> bool:
        now = self.clock() if now_mono is None else float(now_mono)
        interval = self.interval_for(state)
        with self._lock:
            last = self._last.get(str(key))
        return last is None or now - last >= interval - 1e-9

    def mark_checked(self, key: str, *, now_mono: float | None = None) -> None:
        now = self.clock() if now_mono is None else float(now_mono)
        with self._lock:
            self._last[str(key)] = now

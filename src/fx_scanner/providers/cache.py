from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Generic, TypeVar

from .semantics import ProviderResult, ProviderStatus

T = TypeVar("T")


@dataclass(slots=True)
class _CacheEntry(Generic[T]):
    result: ProviderResult[T]
    expires_at: float


class ProviderCache:
    """Bounded semantic TTL cache with short negative/stale caching."""

    def __init__(
        self,
        *,
        positive_ttl_seconds: float = 300,
        negative_ttl_seconds: float = 60,
        stale_ttl_seconds: float = 30,
        max_entries: int = 2048,
        clock=monotonic,
    ):
        values = (positive_ttl_seconds, negative_ttl_seconds, stale_ttl_seconds)
        if any(isinstance(v, bool) for v in values) or isinstance(max_entries, bool):
            raise ValueError("provider cache limits cannot be boolean")
        if any(float(v) <= 0 for v in values) or max_entries <= 0:
            raise ValueError("provider cache limits must be positive")
        self.positive_ttl_seconds = float(positive_ttl_seconds)
        self.negative_ttl_seconds = float(negative_ttl_seconds)
        self.stale_ttl_seconds = float(stale_ttl_seconds)
        self.max_entries = int(max_entries)
        self.clock = clock
        self._lock = RLock()
        self._entries: dict[str, _CacheEntry] = {}

    def _ttl(self, result: ProviderResult) -> float:
        if result.status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL}:
            return self.positive_ttl_seconds
        if result.status == ProviderStatus.STALE:
            return self.stale_ttl_seconds
        return self.negative_ttl_seconds

    def get(self, key: str):
        now = self.clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now >= entry.expires_at:
                self._entries.pop(key, None)
                return None
            return entry.result

    def put(self, key: str, result: ProviderResult) -> None:
        now = self.clock()
        with self._lock:
            if key not in self._entries and len(self._entries) >= self.max_entries:
                victim = min(self._entries, key=lambda k: self._entries[k].expires_at)
                self._entries.pop(victim, None)
            self._entries[key] = _CacheEntry(result, now + self._ttl(result))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

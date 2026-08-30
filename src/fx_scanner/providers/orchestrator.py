from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from ..exceptions import DataContractError
from .cache import ProviderCache
from .semantics import (
    NumericObservation,
    ProviderErrorCategory,
    ProviderResult,
    ProviderStatus,
    Provenance,
)


@dataclass(frozen=True, slots=True)
class QuorumNumericResult:
    status: ProviderStatus
    value: float | None
    coverage: float
    sources_used: tuple[str, ...]
    source_results: tuple[ProviderResult[NumericObservation], ...]
    conflict_span: float | None


class ProviderOrchestrator:
    """Deterministic provider fan-in with semantic caching and conflict checks."""

    def __init__(
        self,
        *,
        cache: ProviderCache | None = None,
        minimum_success: int = 1,
        maximum_numeric_conflict: float = 10.0,
    ):
        if isinstance(minimum_success, bool) or isinstance(maximum_numeric_conflict, bool):
            raise ValueError("provider quorum configuration cannot be boolean")
        if minimum_success <= 0 or maximum_numeric_conflict < 0:
            raise ValueError("invalid provider quorum configuration")
        self.cache = cache or ProviderCache()
        self.minimum_success = int(minimum_success)
        self.maximum_numeric_conflict = float(maximum_numeric_conflict)

    def fetch(self, provider, series: str, *, max_age_seconds: float | None = None):
        key = f"{provider.name}:{series}:{max_age_seconds}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        result = provider.fetch_numeric(series, max_age_seconds=max_age_seconds)
        self.cache.put(key, result)
        return result

    def collect_numeric(
        self,
        bindings: Iterable[tuple[object, str]],
        *,
        max_age_seconds: float | None = None,
    ) -> QuorumNumericResult:
        bindings = tuple(bindings)
        if not bindings:
            raise DataContractError("provider quorum requires at least one binding")

        results = tuple(
            self.fetch(provider, series, max_age_seconds=max_age_seconds)
            for provider, series in bindings
        )
        usable = [r for r in results if r.usable and r.value is not None]
        coverage = len(usable) / len(results)

        if len(usable) < self.minimum_success:
            statuses = {r.status for r in results}
            if ProviderStatus.INVALID in statuses:
                blocked_status = ProviderStatus.INVALID
            elif ProviderStatus.STALE in statuses:
                blocked_status = ProviderStatus.STALE
            elif ProviderStatus.ERROR in statuses:
                blocked_status = ProviderStatus.ERROR
            else:
                blocked_status = ProviderStatus.MISSING
            return QuorumNumericResult(
                blocked_status,
                None,
                coverage,
                (),
                results,
                None,
            )

        values = [float(r.value.value) for r in usable]
        span = max(values) - min(values) if len(values) > 1 else 0.0
        if span > self.maximum_numeric_conflict:
            return QuorumNumericResult(
                ProviderStatus.INVALID,
                None,
                coverage,
                tuple(sorted(r.provenance.provider for r in usable)),
                results,
                span,
            )

        status = ProviderStatus.AVAILABLE if len(usable) == len(results) else ProviderStatus.PARTIAL
        return QuorumNumericResult(
            status,
            float(median(values)),
            coverage,
            tuple(sorted(r.provenance.provider for r in usable)),
            results,
            span,
        )

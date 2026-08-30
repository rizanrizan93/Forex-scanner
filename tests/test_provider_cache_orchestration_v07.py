from datetime import datetime, timezone

import pytest

from fx_scanner.providers.cache import ProviderCache
from fx_scanner.providers.orchestrator import ProviderOrchestrator
from fx_scanner.providers.semantics import (
    Freshness,
    NumericObservation,
    ProviderErrorCategory,
    ProviderResult,
    ProviderStatus,
    Provenance,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)


class FakeProvider:
    def __init__(self, name, value=None, status=ProviderStatus.AVAILABLE):
        self.name = name
        self.value = value
        self.status = status
        self.calls = 0

    def fetch_numeric(self, series, *, max_age_seconds=None):
        self.calls += 1
        p = Provenance(self.name, f"https://{self.name.lower()}.example/data", series, True)
        if self.status == ProviderStatus.AVAILABLE:
            obs = NumericObservation(series, self.value, NOW)
            fresh = Freshness.evaluate(NOW, NOW, max_age_seconds=max_age_seconds or 60)
            return ProviderResult(self.status, obs, p, fresh)
        if self.status == ProviderStatus.STALE:
            old = datetime(2026, 8, 20, tzinfo=UTC)
            obs = NumericObservation(series, self.value, old)
            fresh = Freshness.evaluate(old, NOW, max_age_seconds=60)
            return ProviderResult(self.status, obs, p, fresh)
        return ProviderResult(
            self.status,
            None,
            p,
            None,
            ProviderErrorCategory.NONE
            if self.status == ProviderStatus.MISSING
            else ProviderErrorCategory.UNAVAILABLE,
        )


def test_provider_cache_uses_shorter_negative_ttl():
    now = [100.0]
    cache = ProviderCache(
        positive_ttl_seconds=30,
        negative_ttl_seconds=5,
        stale_ttl_seconds=2,
        clock=lambda: now[0],
    )
    missing = FakeProvider("MISS", status=ProviderStatus.MISSING).fetch_numeric("X")
    cache.put("x", missing)
    assert cache.get("x") is missing
    now[0] = 105.0
    assert cache.get("x") is None


def test_orchestrator_cache_prevents_duplicate_network_fetch():
    provider = FakeProvider("ONE", 2.5)
    orchestrator = ProviderOrchestrator()
    first = orchestrator.fetch(provider, "X", max_age_seconds=60)
    second = orchestrator.fetch(provider, "X", max_age_seconds=60)
    assert first is second
    assert provider.calls == 1


def test_quorum_median_and_partial_coverage():
    one = FakeProvider("ONE", 10)
    two = FakeProvider("TWO", 20)
    miss = FakeProvider("MISS", status=ProviderStatus.MISSING)
    orchestrator = ProviderOrchestrator(
        minimum_success=2,
        maximum_numeric_conflict=15,
    )
    result = orchestrator.collect_numeric([(one, "X"), (two, "X"), (miss, "X")])
    assert result.status == ProviderStatus.PARTIAL
    assert result.value == pytest.approx(15)
    assert result.coverage == pytest.approx(2 / 3)


def test_quorum_conflict_fails_closed():
    one = FakeProvider("ONE", 0)
    two = FakeProvider("TWO", 50)
    orchestrator = ProviderOrchestrator(
        minimum_success=2,
        maximum_numeric_conflict=10,
    )
    result = orchestrator.collect_numeric([(one, "X"), (two, "X")])
    assert result.status == ProviderStatus.INVALID
    assert result.value is None
    assert result.conflict_span == pytest.approx(50)


def test_quorum_preserves_stale_reason_when_no_fresh_source_exists():
    stale = FakeProvider("STALE", 10, status=ProviderStatus.STALE)
    orchestrator = ProviderOrchestrator(minimum_success=1)
    result = orchestrator.collect_numeric([(stale, "X")])
    assert result.status == ProviderStatus.STALE
    assert result.value is None


def test_boolean_provider_limits_are_rejected():
    with pytest.raises(ValueError, match="boolean"):
        ProviderCache(positive_ttl_seconds=True)
    with pytest.raises(ValueError, match="boolean"):
        ProviderOrchestrator(minimum_success=True)

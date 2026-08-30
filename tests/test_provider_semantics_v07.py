from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.exceptions import DataContractError
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


def prov():
    return Provenance("TEST", "https://example.com/data", "SERIES", True)


def test_zero_is_valid_observation_not_missing():
    obs = NumericObservation("SERIES", 0.0, NOW)
    fresh = Freshness.evaluate(NOW, NOW, max_age_seconds=60)
    result = ProviderResult(ProviderStatus.AVAILABLE, obs, prov(), fresh)
    assert result.usable
    assert result.value.value == 0.0


def test_missing_is_distinct_from_zero_and_need_not_be_error():
    result = ProviderResult(
        ProviderStatus.MISSING,
        None,
        prov(),
        None,
        ProviderErrorCategory.NONE,
        "not published",
    )
    assert not result.usable
    assert result.value is None


def test_stale_value_is_preserved_but_not_usable():
    old = NOW - timedelta(days=3)
    obs = NumericObservation("SERIES", 2.5, old)
    fresh = Freshness.evaluate(old, NOW, max_age_seconds=3600)
    result = ProviderResult(ProviderStatus.STALE, obs, prov(), fresh)
    assert result.value.value == 2.5
    assert not result.usable
    assert fresh.stale


def test_success_cannot_hide_stale_freshness():
    old = NOW - timedelta(days=1)
    fresh = Freshness.evaluate(old, NOW, max_age_seconds=60)
    with pytest.raises(DataContractError, match="stale"):
        ProviderResult(
            ProviderStatus.AVAILABLE,
            NumericObservation("SERIES", 1.0, old),
            prov(),
            fresh,
        )


def test_invalid_result_requires_error_category():
    with pytest.raises(DataContractError, match="requires error category"):
        ProviderResult(ProviderStatus.INVALID, None, prov(), None)

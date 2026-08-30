from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from typing import Generic, TypeVar

from ..exceptions import DataContractError

UTC = timezone.utc
T = TypeVar("T")


class ProviderStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"
    ERROR = "ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProviderErrorCategory(StrEnum):
    NONE = "NONE"
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    HTTP = "HTTP"
    PARSE = "PARSE"
    CONTRACT = "CONTRACT"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class Freshness:
    observed_at: datetime
    fetched_at: datetime
    age_seconds: float
    max_age_seconds: float
    stale: bool

    @classmethod
    def evaluate(
        cls,
        observed_at: datetime,
        fetched_at: datetime,
        *,
        max_age_seconds: float,
    ) -> "Freshness":
        if observed_at.tzinfo is None or fetched_at.tzinfo is None:
            raise DataContractError("provider timestamps must be timezone-aware")
        if max_age_seconds <= 0 or not isfinite(max_age_seconds):
            raise DataContractError("max_age_seconds must be positive finite")
        observed = observed_at.astimezone(UTC)
        fetched = fetched_at.astimezone(UTC)
        age = (fetched - observed).total_seconds()
        if age < -1.0:
            raise DataContractError("provider observation timestamp is in the future")
        age = max(0.0, age)
        return cls(observed, fetched, age, float(max_age_seconds), age > max_age_seconds)


@dataclass(frozen=True, slots=True)
class Provenance:
    provider: str
    source_url: str
    series: str
    official: bool

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.series.strip():
            raise DataContractError("provider provenance requires provider and series")
        if not self.source_url.startswith("https://"):
            raise DataContractError("provider provenance source_url must use HTTPS")


@dataclass(frozen=True, slots=True)
class NumericObservation:
    series: str
    value: float
    observed_at: datetime
    previous_value: float | None = None
    previous_observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.series.strip():
            raise DataContractError("numeric observation series is required")
        if isinstance(self.value, bool) or not isfinite(float(self.value)):
            raise DataContractError("numeric observation value must be finite numeric")
        if self.observed_at.tzinfo is None:
            raise DataContractError("numeric observation timestamp must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        object.__setattr__(self, "value", float(self.value))
        if self.previous_value is not None:
            if isinstance(self.previous_value, bool) or not isfinite(float(self.previous_value)):
                raise DataContractError("previous numeric observation must be finite numeric")
            object.__setattr__(self, "previous_value", float(self.previous_value))
        if self.previous_observed_at is not None:
            if self.previous_observed_at.tzinfo is None:
                raise DataContractError("previous observation timestamp must be timezone-aware")
            object.__setattr__(
                self,
                "previous_observed_at",
                self.previous_observed_at.astimezone(UTC),
            )


@dataclass(frozen=True, slots=True)
class ProviderResult(Generic[T]):
    status: ProviderStatus
    value: T | None
    provenance: Provenance
    freshness: Freshness | None
    error_category: ProviderErrorCategory = ProviderErrorCategory.NONE
    message: str | None = None

    def __post_init__(self) -> None:
        success = self.status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL}
        if success and self.value is None:
            raise DataContractError("successful provider result requires a value")
        if not success and self.status != ProviderStatus.STALE and self.value is not None:
            raise DataContractError("failed provider result cannot carry a successful value")
        if self.status == ProviderStatus.STALE:
            if self.value is None or self.freshness is None or not self.freshness.stale:
                raise DataContractError("STALE provider result requires stale value/freshness")
        if success and self.freshness is not None and self.freshness.stale:
            raise DataContractError("fresh success cannot carry stale freshness")
        if success and self.error_category != ProviderErrorCategory.NONE:
            raise DataContractError("successful provider result cannot carry error category")
        if self.status in {ProviderStatus.INVALID, ProviderStatus.ERROR}:
            if self.error_category == ProviderErrorCategory.NONE:
                raise DataContractError("invalid/error provider result requires error category")
        if self.status in {ProviderStatus.MISSING, ProviderStatus.NOT_APPLICABLE}:
            if self.value is not None:
                raise DataContractError("missing/not-applicable result cannot carry a value")

    @property
    def usable(self) -> bool:
        return self.status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL}

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Mapping, Sequence

from ..exceptions import DataContractError
from ..macro import CurrencyMacroScore, score_currency_macro
from .semantics import ProviderResult, ProviderStatus

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class FactorBinding:
    provider: object
    series: str
    normalizer: object
    max_age_seconds: float

    def __post_init__(self) -> None:
        if not self.series.strip():
            raise DataContractError("factor provider series is required")
        if self.max_age_seconds <= 0:
            raise DataContractError("factor max_age_seconds must be positive")
        if not hasattr(self.provider, "fetch_numeric"):
            raise DataContractError("factor provider must expose fetch_numeric")
        if not hasattr(self.normalizer, "score"):
            raise DataContractError("factor normalizer must expose score")


@dataclass(frozen=True, slots=True)
class FactorEvidence:
    factor: str
    score: float | None
    coverage: float
    status: ProviderStatus
    providers_used: tuple[str, ...]
    missing_or_rejected: tuple[str, ...]
    source_results: tuple[ProviderResult, ...]


@dataclass(frozen=True, slots=True)
class CurrencyMacroBundle:
    currency: str
    observed_at: datetime
    macro: CurrencyMacroScore
    factor_scores: Mapping[str, float | None]
    factor_evidence: Mapping[str, FactorEvidence]


class MacroProviderPipeline:
    """Provider -> normalized factor evidence -> v0.6 macro scorer."""

    def __init__(
        self,
        orchestrator,
        *,
        factor_quorum: int = 1,
        maximum_score_conflict: float = 40.0,
        clock=lambda: datetime.now(tz=UTC),
    ):
        if factor_quorum <= 0 or maximum_score_conflict < 0:
            raise ValueError("invalid macro provider pipeline quorum")
        self.orchestrator = orchestrator
        self.factor_quorum = int(factor_quorum)
        self.maximum_score_conflict = float(maximum_score_conflict)
        self.clock = clock

    def _collect_factor(
        self,
        factor: str,
        bindings: Sequence[FactorBinding],
    ) -> FactorEvidence:
        if not bindings:
            return FactorEvidence(
                factor,
                None,
                0.0,
                ProviderStatus.MISSING,
                (),
                (),
                (),
            )

        source_results: list[ProviderResult] = []
        normalized: list[tuple[str, float]] = []
        rejected: list[str] = []

        for binding in bindings:
            result = self.orchestrator.fetch(
                binding.provider,
                binding.series,
                max_age_seconds=binding.max_age_seconds,
            )
            source_results.append(result)
            provider_name = result.provenance.provider
            if not result.usable or result.value is None:
                rejected.append(f"{provider_name}:{result.status.value}")
                continue
            try:
                score = binding.normalizer.score(result.value)
            except DataContractError:
                rejected.append(f"{provider_name}:NORMALIZATION_ERROR")
                continue
            if score is None:
                rejected.append(f"{provider_name}:INSUFFICIENT_HISTORY")
                continue
            if isinstance(score, bool):
                rejected.append(f"{provider_name}:NORMALIZATION_BOOLEAN")
                continue
            score = float(score)
            if not -100 <= score <= 100:
                rejected.append(f"{provider_name}:OUT_OF_RANGE")
                continue
            normalized.append((provider_name, score))

        coverage = len(normalized) / len(bindings)
        if len(normalized) < self.factor_quorum:
            return FactorEvidence(
                factor,
                None,
                coverage,
                ProviderStatus.MISSING,
                (),
                tuple(sorted(rejected)),
                tuple(source_results),
            )

        values = [score for _, score in normalized]
        span = max(values) - min(values) if len(values) > 1 else 0.0
        if span > self.maximum_score_conflict:
            return FactorEvidence(
                factor,
                None,
                coverage,
                ProviderStatus.INVALID,
                tuple(sorted(name for name, _ in normalized)),
                tuple(sorted(rejected + [f"CONFLICT_SPAN:{span:.6f}"])),
                tuple(source_results),
            )

        status = (
            ProviderStatus.AVAILABLE
            if len(normalized) == len(bindings)
            else ProviderStatus.PARTIAL
        )
        return FactorEvidence(
            factor,
            float(median(values)),
            coverage,
            status,
            tuple(sorted(name for name, _ in normalized)),
            tuple(sorted(rejected)),
            tuple(source_results),
        )

    def collect_currency(
        self,
        currency: str,
        *,
        bindings_by_factor: Mapping[str, Sequence[FactorBinding]],
        weights: Mapping[str, float],
        minimum_macro_coverage: float,
        factor_min: float = -100.0,
        factor_max: float = 100.0,
    ) -> CurrencyMacroBundle:
        expected = set(weights)
        unknown = set(bindings_by_factor) - expected
        if unknown:
            raise DataContractError(f"unknown macro factor bindings: {sorted(unknown)}")

        evidence = {
            factor: self._collect_factor(factor, tuple(bindings_by_factor.get(factor, ())))
            for factor in weights
        }
        factor_scores = {
            factor: item.score
            if item.status in {ProviderStatus.AVAILABLE, ProviderStatus.PARTIAL}
            else None
            for factor, item in evidence.items()
        }
        macro = score_currency_macro(
            currency,
            factor_scores,
            weights,
            minimum_coverage=minimum_macro_coverage,
            factor_min=factor_min,
            factor_max=factor_max,
        )
        observed_at = self.clock()
        if observed_at.tzinfo is None:
            raise DataContractError("macro pipeline clock must be timezone-aware")
        return CurrencyMacroBundle(
            currency.upper(),
            observed_at.astimezone(UTC),
            macro,
            factor_scores,
            evidence,
        )

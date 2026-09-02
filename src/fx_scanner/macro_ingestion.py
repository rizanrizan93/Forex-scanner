from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .config import ProjectConfig
from .providers.factory import ProviderRuntime, build_provider_runtime
from .providers.normalization import DeltaNormalizer
from .providers.pipeline import FactorBinding, MacroProviderPipeline

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class MacroRefreshReport:
    observed_at: datetime
    currencies_total: int
    valid_currencies: int
    coverage_by_currency: Mapping[str, float]
    missing_by_currency: Mapping[str, tuple[str, ...]]
    status_by_currency: Mapping[str, str]


class MacroEvidenceRefresher:
    """Refresh durable official macro evidence without inventing missing factors."""

    def __init__(
        self,
        cfg: ProjectConfig,
        store: Any,
        *,
        runtime: ProviderRuntime | Any | None = None,
        clock=lambda: datetime.now(tz=UTC),
    ):
        self.cfg = cfg
        self.store = store
        self.runtime = runtime or build_provider_runtime(cfg.providers)
        self.clock = clock

    def _bindings(self, currency: str) -> dict[str, tuple[FactorBinding, ...]]:
        ingestion = self.cfg.providers["macro_ingestion"]
        default_area = str(ingestion["currency_areas"][currency])
        output: dict[str, tuple[FactorBinding, ...]] = {}
        for factor, item in ingestion["factors"].items():
            area_overrides = item.get("area_overrides", {})
            area = str(area_overrides.get(currency, default_area))
            key_overrides = item.get("key_overrides", {})
            key_template = str(key_overrides.get(currency, item["key_template"]))
            key = key_template.format(area=area)
            series = f"{item['dataset']}|{key}"
            provider = self.runtime.providers[str(item["provider"])]
            normalizer = DeltaNormalizer(
                scale=float(item["scale"]),
                polarity=int(item["polarity"]),
            )
            output[str(factor)] = (
                FactorBinding(
                    provider,
                    series,
                    normalizer,
                    float(item["max_age_seconds"]),
                ),
            )
        return output


    def prefetch_sources(self, currencies: list[str] | tuple[str, ...]) -> None:
        """Prime provider cache using batched official-source requests when supported."""
        groups: dict[tuple[int, float], dict[str, tuple[object, FactorBinding]]] = {}
        for currency in currencies:
            for factor, bindings in self._bindings(currency).items():
                for binding in bindings:
                    provider = binding.provider
                    if not hasattr(provider, "fetch_numeric_batch"):
                        continue
                    label = f"{currency}:{factor}:{binding.series}"
                    key = (id(provider), float(binding.max_age_seconds))
                    groups.setdefault(key, {})[label] = (provider, binding)

        for (_provider_id, max_age), members in groups.items():
            provider = next(iter(members.values()))[0]
            series_by_label = {
                label: binding.series
                for label, (_provider, binding) in members.items()
            }
            results = provider.fetch_numeric_batch(
                series_by_label,
                max_age_seconds=max_age,
            )
            for label, (_provider, binding) in members.items():
                result = results.get(label)
                if result is None:
                    continue
                self.runtime.orchestrator.prime(
                    provider,
                    binding.series,
                    result,
                    max_age_seconds=binding.max_age_seconds,
                )

    def run_once(self) -> MacroRefreshReport:
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("macro refresher clock must be timezone-aware")
        now = now.astimezone(UTC)
        pipeline = MacroProviderPipeline(
            self.runtime.orchestrator,
            clock=lambda: now,
        )
        currencies = sorted(self.cfg.providers["macro_ingestion"]["currency_areas"])
        self.prefetch_sources(currencies)
        coverage: dict[str, float] = {}
        missing: dict[str, tuple[str, ...]] = {}
        statuses: dict[str, str] = {}
        valid = 0
        for currency in currencies:
            bundle = pipeline.collect_currency(
                currency,
                bindings_by_factor=self._bindings(currency),
                weights=self.cfg.macro["weights"],
                minimum_macro_coverage=float(self.cfg.macro["minimum_coverage"]),
                factor_min=float(self.cfg.macro["factor_min"]),
                factor_max=float(self.cfg.macro["factor_max"]),
            )
            self.store.write_currency_macro_bundle(bundle)
            coverage[currency] = float(bundle.macro.coverage)
            missing[currency] = tuple(bundle.macro.missing_factors)
            statuses[currency] = bundle.macro.status.value
            if bundle.macro.score is not None:
                valid += 1
        return MacroRefreshReport(
            observed_at=now,
            currencies_total=len(currencies),
            valid_currencies=valid,
            coverage_by_currency=coverage,
            missing_by_currency=missing,
            status_by_currency=statuses,
        )

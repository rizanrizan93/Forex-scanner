from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from ..exceptions import ConfigurationError, FXScannerError, MissingOptionalDependency
from ..providers.pipeline import CurrencyMacroBundle

UTC = timezone.utc


class ResearchStoreUnavailable(FXScannerError):
    """Durable research persistence failed."""


class SupabaseResearchStore:
    """Backend-only writer for non-latency-critical research state."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        *,
        client: Any | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        if not url.strip():
            raise ConfigurationError("SUPABASE_URL is required")
        if not secret_key.strip():
            raise ConfigurationError("SUPABASE_SECRET_KEY is required")
        self.url = url.strip()
        if client is not None:
            self.client = client
            return
        if client_factory is None:
            try:
                from supabase import create_client
            except ModuleNotFoundError as exc:
                raise MissingOptionalDependency("supabase package is unavailable") from exc
            client_factory = create_client
        self.client = client_factory(self.url, secret_key)

    @classmethod
    def from_env(cls, **kwargs) -> "SupabaseResearchStore":
        url = os.getenv("SUPABASE_URL", "").strip()
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not secret:
            secret = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        return cls(url, secret, **kwargs)

    @staticmethod
    def _factor_evidence(bundle: CurrencyMacroBundle) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for factor, evidence in bundle.factor_evidence.items():
            sources: list[dict[str, Any]] = []
            for result in evidence.source_results:
                freshness = result.freshness
                sources.append(
                    {
                        "provider": result.provenance.provider,
                        "series": result.provenance.series,
                        "source_url": result.provenance.source_url,
                        "official": result.provenance.official,
                        "status": result.status.value,
                        "error_category": result.error_category.value,
                        "message": result.message,
                        "age_seconds": None if freshness is None else freshness.age_seconds,
                        "max_age_seconds": None if freshness is None else freshness.max_age_seconds,
                    }
                )
            out[factor] = {
                "score": evidence.score,
                "coverage": evidence.coverage,
                "status": evidence.status.value,
                "providers_used": list(evidence.providers_used),
                "missing_or_rejected": list(evidence.missing_or_rejected),
                "sources": sources,
            }
        return out

    @staticmethod
    def _freshness_seconds(bundle: CurrencyMacroBundle) -> int:
        ages: list[float] = []
        for evidence in bundle.factor_evidence.values():
            for result in evidence.source_results:
                if result.freshness is not None:
                    ages.append(float(result.freshness.age_seconds))
        return int(max(ages, default=0.0))

    def write_currency_macro_bundle(self, bundle: CurrencyMacroBundle) -> None:
        factor_scores: Mapping[str, float | None] = bundle.factor_scores
        row = {
            "currency": bundle.currency,
            "observed_at": bundle.observed_at.astimezone(UTC).isoformat(),
            "rate_score": factor_scores.get("interest_rate"),
            "central_bank_score": factor_scores.get("central_bank_bias"),
            "inflation_score": factor_scores.get("inflation"),
            "growth_score": factor_scores.get("growth"),
            "labour_score": factor_scores.get("labour"),
            "yield_score": factor_scores.get("yield_momentum"),
            "risk_score": factor_scores.get("risk_commodity"),
            "positioning_score": factor_scores.get("positioning"),
            "macro_score": bundle.macro.score,
            "coverage": bundle.macro.coverage,
            "freshness_seconds": self._freshness_seconds(bundle),
            "evidence": self._factor_evidence(bundle),
        }
        try:
            (
                self.client.table("currency_macro_state")
                .upsert(row, on_conflict="currency,observed_at")
                .execute()
            )
        except Exception as exc:
            raise ResearchStoreUnavailable(
                f"currency_macro_state write failed: {exc}"
            ) from exc

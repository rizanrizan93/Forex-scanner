from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..exceptions import ConfigurationError
from .cache import ProviderCache
from .official import BankOfCanadaValetProvider, EcbDataPortalProvider, FredCsvProvider, RbaCashRateProvider
from .orchestrator import ProviderOrchestrator
from .transport import UrllibHttpTransport


@dataclass(frozen=True, slots=True)
class ProviderRuntime:
    transport: UrllibHttpTransport
    cache: ProviderCache
    orchestrator: ProviderOrchestrator
    providers: Mapping[str, object]


def build_provider_runtime(provider_config: Mapping[str, Any]) -> ProviderRuntime:
    transport_cfg = provider_config["transport"]
    cache_cfg = provider_config["cache"]
    quorum_cfg = provider_config["quorum"]
    sources = provider_config["sources"]

    transport = UrllibHttpTransport(
        timeout_seconds=float(transport_cfg["timeout_seconds"]),
        max_response_bytes=int(transport_cfg["max_response_bytes"]),
        user_agent=str(transport_cfg["user_agent"]),
    )
    cache = ProviderCache(
        positive_ttl_seconds=float(cache_cfg["positive_ttl_seconds"]),
        negative_ttl_seconds=float(cache_cfg["negative_ttl_seconds"]),
        stale_ttl_seconds=float(cache_cfg["stale_ttl_seconds"]),
    )
    orchestrator = ProviderOrchestrator(
        cache=cache,
        minimum_success=int(quorum_cfg["minimum_success"]),
        maximum_numeric_conflict=float(quorum_cfg["maximum_numeric_conflict"]),
    )

    ecb_cfg = sources["ECB_DATA_PORTAL"]
    boc_cfg = sources["BANK_OF_CANADA_VALET"]
    fred_cfg = sources["FEDERAL_RESERVE_FRED"]
    rba_cfg = sources["RBA_CASH_RATE"]
    providers: dict[str, object] = {
        "ECB_DATA_PORTAL": EcbDataPortalProvider(
            transport,
            base_url=str(ecb_cfg["base_url"]),
            allowed_host=str(ecb_cfg["allowed_host"]),
            default_max_age_seconds=float(ecb_cfg["default_max_age_seconds"]),
        ),
        "BANK_OF_CANADA_VALET": BankOfCanadaValetProvider(
            transport,
            base_url=str(boc_cfg["base_url"]),
            allowed_host=str(boc_cfg["allowed_host"]),
            default_max_age_seconds=float(boc_cfg["default_max_age_seconds"]),
        ),
        "FEDERAL_RESERVE_FRED": FredCsvProvider(
            transport,
            base_url=str(fred_cfg["base_url"]),
            allowed_host=str(fred_cfg["allowed_host"]),
            default_max_age_seconds=float(fred_cfg["default_max_age_seconds"]),
        ),
        "RBA_CASH_RATE": RbaCashRateProvider(
            transport,
            base_url=str(rba_cfg["base_url"]),
            allowed_host=str(rba_cfg["allowed_host"]),
            default_max_age_seconds=float(rba_cfg["default_max_age_seconds"]),
        ),
    }
    unknown = set(sources) - set(providers)
    if unknown:
        raise ConfigurationError(f"provider runtime has unsupported sources: {sorted(unknown)}")
    return ProviderRuntime(transport, cache, orchestrator, providers)

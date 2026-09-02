from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.macro_ingestion import MacroEvidenceRefresher
from fx_scanner.providers.cache import ProviderCache
from fx_scanner.providers.official import OecdSdmxCsvProvider
from fx_scanner.providers.orchestrator import ProviderOrchestrator
from fx_scanner.providers.semantics import (
    Freshness,
    NumericObservation,
    ProviderResult,
    ProviderStatus,
    Provenance,
)
from fx_scanner.providers.transport import HttpResponse

UTC = timezone.utc
NOW = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


class FakeTransport:
    def __init__(self, body: bytes):
        self.body = body
        self.calls = []

    def get(self, url, *, allowed_host, headers=None):
        self.calls.append((url, allowed_host, dict(headers or {})))
        return HttpResponse(200, self.body, {}, url)


def test_oecd_provider_reads_last_two_exact_csv_observations():
    body = (
        b"REF_AREA,FREQ,MEASURE,TIME_PERIOD,OBS_VALUE\n"
        b"USA,M,IRLT,2026-06,4.10\n"
        b"USA,M,IRLT,2026-07,4.25\n"
    )
    transport = FakeTransport(body)
    provider = OecdSdmxCsvProvider(transport, clock=lambda: NOW)
    result = provider.fetch_numeric(
        "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0|USA.M.IRLT.PA.....",
        max_age_seconds=10368000,
    )
    assert result.status == ProviderStatus.AVAILABLE
    assert result.value.value == pytest.approx(4.25)
    assert result.value.previous_value == pytest.approx(4.10)
    assert result.value.observed_at == datetime(2026, 7, 31, tzinfo=UTC)
    assert transport.calls[0][1] == "sdmx.oecd.org"
    assert "format=csvfile" in transport.calls[0][0]
    assert "startPeriod=" in transport.calls[0][0]


def test_oecd_provider_rejects_non_exact_or_ambiguous_contract():
    provider = OecdSdmxCsvProvider(FakeTransport(b""), clock=lambda: NOW)
    invalid = provider.fetch_numeric("https://evil.example/data")
    assert invalid.status == ProviderStatus.INVALID

    ambiguous = OecdSdmxCsvProvider(
        FakeTransport(
            b"TIME_PERIOD,OBS_VALUE\n"
            b"2026-07,1.0\n"
            b"2026-07,2.0\n"
        ),
        clock=lambda: NOW,
    ).fetch_numeric(
        "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0|USA.M.IRLT.PA....."
    )
    assert ambiguous.status == ProviderStatus.INVALID


class AlwaysFreshOecd:
    name = "OECD_SDMX"

    def __init__(self, *, with_history=True):
        self.with_history = with_history

    def fetch_numeric(self, series, *, max_age_seconds=None):
        observation = NumericObservation(
            series,
            2.50,
            NOW - timedelta(days=10),
            2.25 if self.with_history else None,
            NOW - timedelta(days=40) if self.with_history else None,
        )
        fresh = Freshness.evaluate(
            observation.observed_at,
            NOW,
            max_age_seconds=max_age_seconds or 10368000,
        )
        return ProviderResult(
            ProviderStatus.AVAILABLE,
            observation,
            Provenance(
                "OECD_SDMX",
                "https://sdmx.oecd.org/public/rest/data",
                series,
                True,
            ),
            fresh,
        )


class Store:
    def __init__(self):
        self.bundles = []

    def write_currency_macro_bundle(self, bundle):
        self.bundles.append(bundle)


def runtime(provider):
    return SimpleNamespace(
        providers={"OECD_SDMX": provider},
        orchestrator=ProviderOrchestrator(cache=ProviderCache()),
    )


def test_macro_refresher_can_reach_exact_70pct_without_synthetic_factors():
    cfg = load_project_config()
    store = Store()
    report = MacroEvidenceRefresher(
        cfg,
        store,
        runtime=runtime(AlwaysFreshOecd()),
        clock=lambda: NOW,
    ).run_once()

    assert report.valid_currencies == 8
    assert len(store.bundles) == 8
    for value in report.coverage_by_currency.values():
        assert value == pytest.approx(0.70)
    for bundle in store.bundles:
        assert bundle.macro.score is not None
        assert bundle.macro.coverage == pytest.approx(0.70)
        assert set(bundle.macro.missing_factors) == {
            "central_bank_bias",
            "positioning",
            "risk_commodity",
        }


def test_macro_refresher_missing_history_stays_missing_not_zero():
    cfg = load_project_config()
    store = Store()
    report = MacroEvidenceRefresher(
        cfg,
        store,
        runtime=runtime(AlwaysFreshOecd(with_history=False)),
        clock=lambda: NOW,
    ).run_once()

    assert report.valid_currencies == 0
    assert all(value == 0.0 for value in report.coverage_by_currency.values())
    assert all(bundle.macro.score is None for bundle in store.bundles)


def test_macro_ingestion_config_preserves_threshold_and_official_source():
    cfg = load_project_config()
    source = cfg.providers["sources"]["OECD_SDMX"]
    assert source["official"] is True
    assert source["base_url"] == "https://sdmx.oecd.org/public/rest/data"
    factor_weight = sum(
        cfg.macro["weights"][factor]
        for factor in cfg.providers["macro_ingestion"]["factors"]
    ) / 100.0
    assert factor_weight == pytest.approx(0.70)
    assert cfg.macro["minimum_coverage"] == pytest.approx(0.70)

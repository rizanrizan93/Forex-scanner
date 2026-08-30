from datetime import datetime, timedelta, timezone

from fx_scanner.config import load_project_config
from fx_scanner.providers.normalization import DeltaNormalizer
from fx_scanner.providers.orchestrator import ProviderOrchestrator
from fx_scanner.providers.pipeline import FactorBinding, MacroProviderPipeline
from fx_scanner.providers.semantics import Freshness, NumericObservation, ProviderResult, ProviderStatus, Provenance
from fx_scanner.storage.supabase_research import SupabaseResearchStore

UTC = timezone.utc
NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.payload = None
        self.conflict = None

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.conflict = on_conflict
        return self

    def execute(self):
        self.client.writes.append((self.table_name, self.payload, self.conflict))
        return Response([self.payload])


class FakeClient:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return Query(self, name)


class Provider:
    name = "OFFICIAL"

    def fetch_numeric(self, series, *, max_age_seconds=None):
        obs = NumericObservation(
            series,
            2.50,
            NOW - timedelta(hours=1),
            2.25,
            NOW - timedelta(days=1),
        )
        fresh = Freshness.evaluate(
            obs.observed_at,
            NOW,
            max_age_seconds=max_age_seconds or 86400,
        )
        return ProviderResult(
            ProviderStatus.AVAILABLE,
            obs,
            Provenance(
                self.name,
                "https://example.com/data",
                series,
                True,
            ),
            fresh,
        )


def bundle():
    cfg = load_project_config()
    pipeline = MacroProviderPipeline(
        ProviderOrchestrator(),
        clock=lambda: NOW,
    )
    return pipeline.collect_currency(
        "CAD",
        bindings_by_factor={
            "interest_rate": [
                FactorBinding(
                    Provider(),
                    "RATE",
                    DeltaNormalizer(scale=0.25),
                    86400,
                )
            ]
        },
        weights=cfg.macro["weights"],
        minimum_macro_coverage=cfg.macro["minimum_coverage"],
    )


def test_supabase_research_store_writes_macro_evidence():
    client = FakeClient()
    store = SupabaseResearchStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )
    store.write_currency_macro_bundle(bundle())

    table, row, conflict = client.writes[0]
    assert table == "currency_macro_state"
    assert conflict == "currency,observed_at"
    assert row["currency"] == "CAD"
    assert row["rate_score"] == 100
    assert row["macro_score"] is None
    assert row["coverage"] == 0.25
    assert row["freshness_seconds"] == 3600
    evidence = row["evidence"]["interest_rate"]
    assert evidence["status"] == "AVAILABLE"
    assert evidence["providers_used"] == ["OFFICIAL"]
    assert evidence["sources"][0]["official"] is True
    assert evidence["sources"][0]["series"] == "RATE"

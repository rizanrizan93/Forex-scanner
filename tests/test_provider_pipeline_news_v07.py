from datetime import datetime, timedelta, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.providers.news import (
    EconomicEvent,
    EventImpact,
    evaluate_news_block,
)
from fx_scanner.providers.normalization import DeltaNormalizer, LevelNormalizer
from fx_scanner.providers.orchestrator import ProviderOrchestrator
from fx_scanner.providers.pipeline import FactorBinding, MacroProviderPipeline
from fx_scanner.providers.semantics import (
    Freshness,
    NumericObservation,
    ProviderResult,
    ProviderStatus,
    Provenance,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)


class SeriesProvider:
    def __init__(self, name, current, previous=None):
        self.name = name
        self.current = current
        self.previous = previous

    def fetch_numeric(self, series, *, max_age_seconds=None):
        obs = NumericObservation(
            series,
            self.current,
            NOW,
            self.previous,
            NOW - timedelta(days=1) if self.previous is not None else None,
        )
        fresh = Freshness.evaluate(NOW, NOW, max_age_seconds=max_age_seconds or 60)
        return ProviderResult(
            ProviderStatus.AVAILABLE,
            obs,
            Provenance(self.name, f"https://{self.name.lower()}.example/data", series, True),
            fresh,
        )


def test_delta_normalizer_does_not_invent_neutral_without_history():
    obs = NumericObservation("X", 2.5, NOW)
    assert DeltaNormalizer(scale=0.25).score(obs) is None


def test_delta_and_level_normalizers_clip_to_signed_100():
    obs = NumericObservation("X", 3.0, NOW, 2.0, NOW - timedelta(days=1))
    assert DeltaNormalizer(scale=0.25).score(obs) == 100
    assert LevelNormalizer(reference=2.0, scale=0.5).score(obs) == 100
    assert LevelNormalizer(reference=2.0, scale=0.5, polarity=-1).score(obs) == -100


def test_macro_pipeline_preserves_missing_factor_history():
    cfg = load_project_config()
    pipeline = MacroProviderPipeline(ProviderOrchestrator())
    binding = FactorBinding(
        SeriesProvider("RATE", 2.25, previous=None),
        "RATE",
        DeltaNormalizer(scale=0.25),
        86400,
    )
    bundle = pipeline.collect_currency(
        "CAD",
        bindings_by_factor={"interest_rate": [binding]},
        weights=cfg.macro["weights"],
        minimum_macro_coverage=cfg.macro["minimum_coverage"],
    )
    assert bundle.factor_scores["interest_rate"] is None
    assert bundle.macro.score is None
    assert bundle.macro.coverage == 0.0


def test_macro_pipeline_scores_available_factor_but_macro_stays_partial_below_70pct():
    cfg = load_project_config()
    pipeline = MacroProviderPipeline(ProviderOrchestrator())
    binding = FactorBinding(
        SeriesProvider("RATE", 2.50, previous=2.25),
        "RATE",
        DeltaNormalizer(scale=0.25),
        86400,
    )
    bundle = pipeline.collect_currency(
        "CAD",
        bindings_by_factor={"interest_rate": [binding]},
        weights=cfg.macro["weights"],
        minimum_macro_coverage=cfg.macro["minimum_coverage"],
    )
    assert bundle.factor_scores["interest_rate"] == 100
    assert bundle.macro.score is None
    assert bundle.macro.coverage == pytest.approx(0.25)


def test_news_block_only_for_relevant_high_impact_currency_window():
    event = EconomicEvent(
        "US-CPI",
        "US CPI",
        "USD",
        NOW + timedelta(minutes=20),
        EventImpact.HIGH,
        "OFFICIAL",
        "https://example.com/calendar",
    )
    result = evaluate_news_block(
        now=NOW,
        currencies=("EUR", "USD"),
        events=(event,),
        pre_block_minutes=30,
        post_block_minutes=30,
    )
    assert result.blocked
    assert result.relevant_events == (event,)

    unrelated = evaluate_news_block(
        now=NOW,
        currencies=("JPY",),
        events=(event,),
    )
    assert not unrelated.blocked


def test_news_block_boundary_is_inclusive():
    event = EconomicEvent(
        "ECB",
        "ECB Decision",
        "EUR",
        NOW,
        EventImpact.HIGH,
        "ECB",
        "https://example.com/ecb",
    )
    at_pre = evaluate_news_block(
        now=NOW - timedelta(minutes=30),
        currencies=("EUR",),
        events=(event,),
    )
    at_post = evaluate_news_block(
        now=NOW + timedelta(minutes=30),
        currencies=("EUR",),
        events=(event,),
    )
    assert at_pre.blocked and at_post.blocked


def test_boolean_normalizer_polarity_and_factor_age_are_rejected():
    from fx_scanner.exceptions import DataContractError

    with pytest.raises(DataContractError, match="polarity"):
        DeltaNormalizer(scale=1.0, polarity=True)
    with pytest.raises(DataContractError, match="max_age_seconds"):
        FactorBinding(
            SeriesProvider("RATE", 2.5, previous=2.25),
            "RATE",
            DeltaNormalizer(scale=0.25),
            True,
        )

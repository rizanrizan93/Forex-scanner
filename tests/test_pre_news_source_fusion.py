from datetime import UTC, datetime

from fx_scanner.pre_news_source_fusion import (
    SOURCE_INVESTING,
    SOURCE_MYFXBOOK,
    SourceQuote,
    canonical_event_key,
    fuse_consensus,
    group_and_fuse,
)


def _at():
    return datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def test_investing_and_myfxbook_cpi_aliases_match():
    assert canonical_event_key("Core CPI (MoM) (Sep)") == "CORE_CPI_MOM"
    assert canonical_event_key("Core Inflation Rate MoM (Sep)") == "CORE_CPI_MOM"
    assert canonical_event_key("Core CPI (YoY) (Sep)") == "CORE_CPI_YOY"
    assert canonical_event_key("Core Inflation Rate YoY (Sep)") == "CORE_CPI_YOY"
    assert canonical_event_key("CPI (MoM) (Sep)") == "CPI_MOM"
    assert canonical_event_key("Inflation Rate MoM (Sep)") == "CPI_MOM"
    assert canonical_event_key("CPI (YoY) (Sep)") == "CPI_YOY"
    assert canonical_event_key("Inflation Rate YoY (Sep)") == "CPI_YOY"


def test_equivalent_provider_consensus_fuses_without_conflict():
    fused = fuse_consensus(
        [
            SourceQuote(
                source=SOURCE_INVESTING,
                title="Core CPI (MoM) (Sep)",
                currency="USD",
                scheduled_at=_at(),
                forecast=0.2,
                previous=0.3,
            ),
            SourceQuote(
                source=SOURCE_MYFXBOOK,
                title="Core Inflation Rate MoM (Sep)",
                currency="USD",
                scheduled_at=_at(),
                forecast=0.2,
                previous=0.3,
            ),
        ]
    )
    assert fused.canonical_key == "CORE_CPI_MOM"
    assert fused.source_agreement == "MULTI_SOURCE_AGREE"
    assert fused.forecast == 0.2
    assert fused.previous == 0.3
    assert not fused.source_conflict


def test_provider_disagreement_is_explicit_conflict():
    fused = fuse_consensus(
        [
            SourceQuote(
                source=SOURCE_INVESTING,
                title="CPI (YoY) (Sep)",
                currency="USD",
                scheduled_at=_at(),
                forecast=3.6,
                previous=3.4,
            ),
            SourceQuote(
                source=SOURCE_MYFXBOOK,
                title="Inflation Rate YoY (Sep)",
                currency="USD",
                scheduled_at=_at(),
                forecast=3.3,
                previous=3.4,
            ),
        ]
    )
    assert fused.source_agreement == "SOURCE_CONFLICT"
    assert "CONSENSUS_CONFLICT" in fused.conflicts


def test_distinct_cpi_components_are_not_collapsed():
    rows = [
        SourceQuote(SOURCE_INVESTING, "Core CPI (MoM) (Sep)", "USD", _at(), 0.2, 0.3),
        SourceQuote(SOURCE_MYFXBOOK, "Core Inflation Rate MoM (Sep)", "USD", _at(), 0.2, 0.3),
        SourceQuote(SOURCE_INVESTING, "CPI (YoY) (Sep)", "USD", _at(), 3.6, 3.4),
        SourceQuote(SOURCE_MYFXBOOK, "Inflation Rate YoY (Sep)", "USD", _at(), 3.6, 3.4),
    ]
    fused = group_and_fuse(rows)
    assert [row.canonical_key for row in fused] == ["CORE_CPI_MOM", "CPI_YOY"]


def test_official_actual_overrides_secondary_actual():
    fused = fuse_consensus(
        [
            SourceQuote(SOURCE_INVESTING, "CPI (MoM)", "USD", _at(), 0.6, 0.4, actual=0.7),
            SourceQuote(SOURCE_MYFXBOOK, "Inflation Rate MoM", "USD", _at(), 0.6, 0.4, actual=0.7),
            SourceQuote("BLS_OFFICIAL", "Consumer Price Index MoM", "USD", _at(), actual=0.5, authoritative_actual=True),
        ]
    )
    assert fused.actual == 0.5


def test_quorum_counts_distinct_numeric_forecasts_not_calendar_rows():
    rows = [
        SourceQuote(SOURCE_INVESTING, "CPI (MoM)", "USD", _at(), 0.2, 0.3),
        SourceQuote(SOURCE_MYFXBOOK, "Inflation Rate MoM", "USD", _at(), 0.2, 0.3),
        SourceQuote("BLS_OFFICIAL_ICS", "Consumer Price Index MoM", "USD", _at()),
    ]
    fused = fuse_consensus(rows)
    assert fused.source_count == 3
    assert fused.forecast_source_count == 2
    assert set(fused.forecast_sources) == {SOURCE_INVESTING, SOURCE_MYFXBOOK}
    assert len(fused.forecast_quotes) == 2
    rows.append(SourceQuote("FOREX_FACTORY_WEEKLY", "CPI (MoM)", "USD", _at(), 0.2, 0.3))
    fused = fuse_consensus(rows)
    assert fused.forecast_source_count == 3


def test_duplicate_provider_never_inflates_forecast_quorum():
    rows = [
        SourceQuote(SOURCE_INVESTING, "CPI (MoM)", "USD", _at(), 0.2, 0.3),
        SourceQuote(SOURCE_INVESTING, "CPI (MoM)", "USD", _at(), 0.4, 0.3),
        SourceQuote(SOURCE_MYFXBOOK, "Inflation Rate MoM", "USD", _at(), 0.2, 0.3),
    ]
    fused = fuse_consensus(rows)
    assert fused.forecast_source_count == 2
    assert "DUPLICATE_SOURCE_FORECAST_CONFLICT" in fused.conflicts


def test_showmytrades_and_helious_real_titles_align_core_vs_headline():
    assert canonical_event_key("Consumer Price Index MoM") == "CPI_MOM"
    assert canonical_event_key("Consumer Price Index (MoM)") == "CPI_MOM"
    assert canonical_event_key("Consumer Price Index ex Food & Energy MoM") == "CORE_CPI_MOM"
    assert canonical_event_key("Consumer Price Index ex Food & Energy (MoM)") == "CORE_CPI_MOM"
    assert canonical_event_key("Producer Price Index ex Food & Energy (MoM)") == "CORE_PPI_MOM"
    assert canonical_event_key("Core PPI (MoM)") == "CORE_PPI_MOM"


def test_realistic_three_sources_fuse_core_separately_from_headline():
    from fx_scanner.pre_news_source_fusion import SOURCE_FOREX_FACTORY
    rows = [
        SourceQuote(SOURCE_FOREX_FACTORY, "Core CPI (MoM)", "USD", _at(), 0.2, 0.3),
        SourceQuote("SHOWMYTRADES", "Consumer Price Index ex Food & Energy MoM", "USD", _at(), 0.2, 0.3),
        SourceQuote("HELIOUS", "Consumer Price Index ex Food & Energy (MoM)", "USD", _at(), 0.2, 0.3),
        SourceQuote("SHOWMYTRADES", "Consumer Price Index MoM", "USD", _at(), 0.3, 0.4),
    ]
    fused = group_and_fuse(rows)
    assert len(fused) == 2
    by_key = {item.canonical_key: item for item in fused}
    assert by_key["CORE_CPI_MOM"].forecast_source_count == 3
    assert by_key["CORE_CPI_MOM"].forecast == 0.2
    assert by_key["CPI_MOM"].forecast_source_count == 1


def test_official_cpi_index_previous_cannot_corrupt_percent_forecast_consensus():
    from fx_scanner.pre_news_source_fusion import SOURCE_FOREX_FACTORY
    values = [
        SourceQuote(SOURCE_FOREX_FACTORY, "CPI (MoM)", "USD", _at(), 0.3, 0.6),
        SourceQuote("SHOWMYTRADES", "Consumer Price Index MoM", "USD", _at(), 0.3, 0.6),
        SourceQuote("HELIOUS", "Consumer Price Index (MoM)", "USD", _at(), 0.3, 0.6),
        SourceQuote("BLS_OFFICIAL_ICS", "Consumer Price Index MoM", "USD", _at(), None, 338.9),
        SourceQuote("BLS_OFFICIAL_ICS", "Consumer Price Index MoM", "USD", _at(), None, 168.77),
    ]
    fused = fuse_consensus(values)
    assert fused.forecast == 0.3
    assert fused.previous == 0.6
    assert fused.forecast_source_count == 3
    assert not fused.conflicts


def test_conflicting_previous_among_forecast_providers_still_blocks_direction():
    from fx_scanner.pre_news_source_fusion import SOURCE_FOREX_FACTORY
    values = [
        SourceQuote(SOURCE_FOREX_FACTORY, "CPI (MoM)", "USD", _at(), 0.3, 0.6),
        SourceQuote("SHOWMYTRADES", "Consumer Price Index MoM", "USD", _at(), 0.3, 0.2),
        SourceQuote("HELIOUS", "Consumer Price Index (MoM)", "USD", _at(), 0.3, 0.6),
    ]
    fused = fuse_consensus(values)
    assert fused.forecast_source_count == 3
    assert "PREVIOUS_CONFLICT" in fused.conflicts


def test_cpi_index_level_mislabeled_mom_is_quarantined_before_fusion():
    """Reproduces Nov 9 Helious rows: index 337 vs CPI MoM 0.3."""
    at = datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
    rows = [
        SourceQuote("FOREX_FACTORY_WEEKLY", "CPI m/m", "USD", at, 0.3, 0.6),
        SourceQuote("SHOWMYTRADES", "Consumer Price Index MoM", "USD", at, 0.3, 0.6),
        SourceQuote("HELIOUS", "Consumer Price Index (MoM)", "USD", at, 337.02, 336.94),
        SourceQuote("HELIOUS", "Consumer Price Index (MoM)", "USD", at, 0.3, 0.6),
    ]
    result = fuse_consensus(rows)
    assert result.forecast == 0.3
    assert result.previous == 0.6
    assert result.forecast_source_count == 3
    assert result.forecast_sources == ("FOREX_FACTORY_WEEKLY", "HELIOUS", "SHOWMYTRADES")
    assert result.rejected_quote_sources == ("HELIOUS",)
    assert result.conflicts == ()
    assert result.source_agreement == "MULTI_SOURCE_AGREE"


def test_cpi_mom_index_only_provider_cannot_satisfy_forecast_quorum():
    at = datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
    result = fuse_consensus([
        SourceQuote("FOREX_FACTORY_WEEKLY", "CPI m/m", "USD", at, 0.3, 0.6),
        SourceQuote("HELIOUS", "Consumer Price Index MoM", "USD", at, 168.66, 168.77),
    ])
    assert result.forecast_source_count == 1
    assert result.forecast == 0.3
    assert result.previous == 0.6
    assert result.rejected_quote_sources == ("HELIOUS",)


def test_cpi_yoy_index_scale_rejected_but_legitimate_rate_kept():
    rows = [
        SourceQuote("HELIOUS", "CPI YoY", "USD", _at(), 337.02, 336.94),
        SourceQuote("SHOWMYTRADES", "CPI YoY", "USD", _at(), 3.9, 3.7),
    ]
    fused = fuse_consensus(rows)
    assert fused.forecast_source_count == 1
    assert fused.forecast == 3.9
    assert fused.rejected_quote_sources == ("HELIOUS",)

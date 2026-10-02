from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_event_risk_v192 import (
    RiskEvent,
    _merge_events,
    evaluate_event_risk,
    parse_bea_schedule,
    parse_bls_ics,
)


def test_parse_bls_ics_uses_eastern_time_and_official_tier():
    body = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260924T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""
    rows = parse_bls_ics(body, source_url="https://www.bls.gov/schedule/news_release/bls.ics")
    assert len(rows) == 1
    event = rows[0]
    assert event.source_tier == "OFFICIAL"
    assert event.category == "CPI"
    assert event.impact == "HIGH"
    assert event.scheduled_at == datetime(2026, 9, 24, 12, 30, tzinfo=UTC)


def test_parse_bea_schedule_extracts_release_row():
    html = b"""
    <table>
      <tr><th>Date</th><th>Time</th><th>Type</th><th>Release</th></tr>
      <tr><td>September 24</td><td>8:30 AM</td><td>News</td>
          <td>U.S. International Transactions and Investment Position, 2nd Quarter 2026</td></tr>
    </table>
    """
    rows = parse_bea_schedule(
        html,
        source_url="https://www.bea.gov/news/schedule",
        now=datetime(2026, 9, 24, 0, 0, tzinfo=UTC),
    )
    assert len(rows) == 1
    event = rows[0]
    assert event.category == "CURRENT_ACCOUNT"
    assert event.source_tier == "OFFICIAL"
    assert event.scheduled_at == datetime(2026, 9, 24, 12, 30, tzinfo=UTC)


def _event(minutes, impact="HIGH", tier="OFFICIAL", category="CPI"):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    at = now + timedelta(minutes=minutes)
    return RiskEvent(
        event_id=f"e-{minutes}",
        title="Test event",
        scheduled_at=at,
        impact=impact,
        category=category,
        source="TEST",
        source_tier=tier,
        source_url="https://example.com/event",
    )


def test_event_risk_pre_event_and_event_window():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    pre = evaluate_event_risk((_event(20),), now=now)
    assert pre["state"] == "PRE_EVENT"
    assert pre["action"] == "PREPARE_ONLY_AVOID_NEW_CHASE"
    live = evaluate_event_risk((_event(5),), now=now)
    assert live["state"] == "EVENT_WINDOW"
    assert live["action"] == "NO_CHASE_WAIT_PRICE_DISCOVERY"
    assert live["execution_authority"] is False


def test_merge_prefers_official_event_for_same_category_and_time():
    now = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    discovery = RiskEvent(
        event_id="d",
        title="Current Account",
        scheduled_at=now,
        impact="MEDIUM",
        category="CURRENT_ACCOUNT",
        source="FOREX_FACTORY_WEEKLY",
        source_tier="DISCOVERY_UNVERIFIED",
        source_url="https://example.com/discovery",
    )
    official = RiskEvent(
        event_id="o",
        title="U.S. International Transactions and Investment Position",
        scheduled_at=now,
        impact="MEDIUM",
        category="CURRENT_ACCOUNT",
        source="BEA_OFFICIAL_SCHEDULE",
        source_tier="OFFICIAL",
        source_url="https://www.bea.gov/news/schedule",
    )
    merged = _merge_events((discovery, official))
    assert len(merged) == 1
    assert merged[0].source_tier == "OFFICIAL"
    assert merged[0].source == "BEA_OFFICIAL_SCHEDULE"


def test_unemployment_claims_is_jobless_claims_category():
    from fx_scanner.demo_xau_event_risk_v192 import _category
    assert _category("Unemployment Claims") == "JOBLESS_CLAIMS"


def test_fomc_member_speech_is_speech_not_fomc_decision():
    from fx_scanner.demo_xau_event_risk_v192 import _category
    assert _category("FOMC Member Williams Speaks") == "FED_SPEECH"



def test_v355_calendar_numeric_parser_handles_common_units():
    from fx_scanner.providers.news import _parse_calendar_number

    assert _parse_calendar_number("90K") == 90_000.0
    assert _parse_calendar_number("3.2%") == 3.2
    assert _parse_calendar_number("-65.2B") == -65_200_000_000.0
    assert _parse_calendar_number("") is None


def test_v355_pre_event_consensus_tilt_is_context_only():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    event = RiskEvent(
        event_id="nfp",
        title="Non-Farm Employment Change",
        scheduled_at=now + timedelta(hours=1),
        impact="HIGH",
        category="EMPLOYMENT",
        source="FOREX_FACTORY_WEEKLY",
        source_tier="DISCOVERY_UNVERIFIED",
        source_url="https://example.com/nfp",
        forecast=130_000.0,
        previous=90_000.0,
    )
    risk = evaluate_event_risk((event,), now=now)
    row = risk["upcoming_events"][0]
    assert row["gold_bias"] == "GOLD_BEARISH"
    assert row["gold_bias_confidence"] == "LOW"
    assert row["gold_bias_basis"] == "CONSENSUS_VS_PREVIOUS"
    assert risk["execution_authority"] is False


def test_v355_actual_vs_forecast_replaces_pre_event_tilt():
    event = RiskEvent(
        event_id="claims",
        title="Unemployment Claims",
        scheduled_at=datetime(2026, 10, 8, 12, 30, tzinfo=UTC),
        impact="MEDIUM",
        category="JOBLESS_CLAIMS",
        source="FOREX_FACTORY_WEEKLY",
        source_tier="OFFICIAL_DOL_CADENCE_MATCHED",
        source_url="https://example.com/claims",
        actual=230_000.0,
        forecast=210_000.0,
        previous=205_000.0,
    )
    row = event.as_dict()
    assert row["gold_bias"] == "GOLD_BULLISH"
    assert row["gold_bias_confidence"] == "POST_RELEASE"
    assert row["gold_bias_basis"] == "ACTUAL_VS_FORECAST"


def test_v355_official_merge_preserves_discovery_forecast_values():
    at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    discovery = RiskEvent(
        event_id="disc",
        title="Non-Farm Employment Change",
        scheduled_at=at,
        impact="HIGH",
        category="EMPLOYMENT",
        source="FOREX_FACTORY_WEEKLY",
        source_tier="DISCOVERY_UNVERIFIED",
        source_url="https://example.com/discovery",
        forecast=90_000.0,
        previous=162_000.0,
    )
    official = RiskEvent(
        event_id="official",
        title="Employment Situation",
        scheduled_at=at,
        impact="HIGH",
        category="EMPLOYMENT",
        source="BLS_OFFICIAL_ICS",
        source_tier="OFFICIAL",
        source_url="https://www.bls.gov/schedule/news_release/bls.ics",
    )
    merged = _merge_events((discovery, official))
    assert len(merged) == 1
    assert merged[0].source_tier == "OFFICIAL"
    assert merged[0].forecast == 90_000.0
    assert merged[0].previous == 162_000.0


def test_v355_event_horizon_includes_next_thirty_days():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    event = RiskEvent(
        event_id="future",
        title="Consumer Price Index",
        scheduled_at=now + timedelta(days=29, hours=23),
        impact="HIGH",
        category="CPI",
        source="BLS_OFFICIAL_ICS",
        source_tier="OFFICIAL",
        source_url="https://www.bls.gov/schedule/news_release/bls.ics",
    )
    risk = evaluate_event_risk((event,), now=now)
    assert len(risk["upcoming_events"]) == 1



def test_v355_labor_components_do_not_collapse_into_one_category():
    from fx_scanner.demo_xau_event_risk_v192 import _category

    assert _category("Non-Farm Employment Change") == "EMPLOYMENT"
    assert _category("Unemployment Rate") == "UNEMPLOYMENT_RATE"
    assert _category("Average Hourly Earnings m/m") == "WAGES"

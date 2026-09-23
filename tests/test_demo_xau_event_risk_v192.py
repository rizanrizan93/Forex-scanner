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

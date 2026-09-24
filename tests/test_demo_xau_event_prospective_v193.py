from datetime import UTC, datetime, timedelta

from fx_scanner.demo_xau_event_prospective_v193 import (
    cluster_upcoming_events,
    historical_ready,
    resolution_state,
)


def test_historical_gate_is_fail_closed():
    assert historical_ready({}) is False
    assert historical_ready({"decision": "BACKFILL_INCOMPLETE"}) is False
    assert historical_ready({"decision": "FULL_BACKFILL_RESEARCH_READY"}) is True


def test_same_time_events_cluster_for_prospective_episode():
    at = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    rows = [
        {
            "event_id": "a",
            "title": "Unemployment Claims",
            "scheduled_at": at.isoformat(),
            "category": "JOBLESS_CLAIMS",
            "impact": "MEDIUM",
            "source": "FF",
            "source_tier": "OFFICIAL_DOL_CADENCE_MATCHED",
        },
        {
            "event_id": "b",
            "title": "Current Account",
            "scheduled_at": (at + timedelta(seconds=30)).isoformat(),
            "category": "CURRENT_ACCOUNT",
            "impact": "MEDIUM",
            "source": "BEA",
            "source_tier": "OFFICIAL",
        },
    ]
    clusters = cluster_upcoming_events(rows)
    assert len(clusters) == 1
    assert clusters[0]["event_count"] == 2
    assert clusters[0]["attribution"] == "MULTI_EVENT_CLUSTER"
    assert set(clusters[0]["families"]) == {"JOBLESS_CLAIMS", "CURRENT_ACCOUNT"}


def test_far_events_do_not_cluster():
    at = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)
    rows = [
        {"title": "CPI", "scheduled_at": at.isoformat(), "category": "CPI"},
        {
            "title": "Fed Speech",
            "scheduled_at": (at + timedelta(minutes=10)).isoformat(),
            "category": "FED_SPEECH",
        },
    ]
    assert len(cluster_upcoming_events(rows)) == 2


def test_resolution_state_advances_only_when_horizon_exists():
    assert resolution_state({}) == "EVENT_OCCURRED_WAIT_REACTION"
    assert resolution_state({"r5m_atr": 0.2}) == "RESOLVED_5M"
    assert resolution_state({"r5m_atr": 0.2, "r15m_atr": -0.1}) == "RESOLVED_15M"
    assert resolution_state({"r30m_atr": 0.4}) == "RESOLVED_30M"
    assert resolution_state({"r60m_atr": -0.5}) == "RESOLVED_60M"

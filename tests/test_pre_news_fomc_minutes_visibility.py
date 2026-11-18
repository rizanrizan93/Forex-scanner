"""Regression for textual FOMC minutes display in the mobile Pre-News dashboard."""
from datetime import UTC, datetime, timedelta

from fx_scanner.pre_news_dashboard import _next_fomc_minutes

NOW = datetime(2026, 11, 18, 7, 36, tzinfo=UTC)


def test_fomc_minutes_is_read_from_live_calendar_without_numeric_actuals():
    release = datetime(2026, 11, 18, 19, 0, tzinfo=UTC)
    items = [
        {"title": "FOMC Member Speaks", "category": "FED_SPEECH",
         "scheduled_at": (NOW + timedelta(hours=1)).isoformat()},
        {"title": "Fed Interest Rate Decision", "category": "FOMC",
         "scheduled_at": (NOW + timedelta(hours=2)).isoformat()},
        {"title": "FOMC Meeting Minutes", "category": "FOMC",
         "scheduled_at": release.isoformat(), "forecast": None, "previous": None,
         "source": "MULTI_SOURCE_FUSION", "impact": "HIGH"},
    ]
    data = {"heartbeats": [
        {"worker_name": "ctrader_demo_xau_event_risk_v192",
         "details": {"risk": {"upcoming_events": items}}},
    ]}
    event = _next_fomc_minutes(data, now=NOW)
    assert event is items[-1]
    assert event["scheduled_at"] == "2026-11-18T19:00:00+00:00"


def test_fomc_minutes_outside_upcoming_week_not_shown():
    data = {"heartbeats": [
        {"worker_name": "ctrader_demo_xau_event_risk_v192",
         "details": {"risk": {"upcoming_events": [
             {"title": "FOMC Meeting Minutes", "category": "FOMC",
              "scheduled_at": (NOW + timedelta(days=9)).isoformat()}
         ]}}}
    ]}
    assert _next_fomc_minutes(data, now=NOW) is None

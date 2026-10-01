from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fx_scanner.xau_news_zone_source_v346 import (
    NewsZoneEvent,
    category_from_title,
)
from fx_scanner.xau_news_zone_v346 import evaluate_news_zone


def _event(at: datetime, category: str = "NFP", impact: str = "HIGH") -> NewsZoneEvent:
    return NewsZoneEvent(
        event_id="e1",
        title="Employment Situation" if category == "NFP" else category,
        scheduled_at=at,
        category=category,
        impact=impact,
        source="TEST",
        source_tier="OFFICIAL",
        source_url="https://example.com/event",
    )


def _bars(start: datetime, rows: list[tuple[float, float, float, float]]):
    return [
        SimpleNamespace(
            timestamp=start + timedelta(minutes=5 * i),
            open=o,
            high=h,
            low=l,
            close=c,
        )
        for i, (o, h, l, c) in enumerate(rows)
    ]


def _sd(micro_confirmed: bool = False):
    return {
        "price_now": 100.5,
        "decision_zone": {
            "zone_id": "d1",
            "timeframe": "H1",
            "direction": "LONG",
            "low": 100.0,
            "high": 101.0,
            "proximal": 100.8,
            "distal": 100.0,
            "atr": 2.0,
        },
        "active_zones": [
            {
                "zone_id": "d1",
                "timeframe": "H1",
                "direction": "LONG",
                "low": 100.0,
                "high": 101.0,
                "proximal": 100.8,
                "distal": 100.0,
                "atr": 2.0,
            },
            {
                "zone_id": "d2",
                "timeframe": "H4",
                "direction": "LONG",
                "low": 96.0,
                "high": 98.0,
                "proximal": 97.5,
                "distal": 96.0,
                "atr": 5.0,
            },
        ],
        "micro_confirmation": {
            "confirmed": micro_confirmed,
            "reclaim_at": "2026-10-02T12:45:00+00:00" if micro_confirmed else None,
        },
        "entry_guide": {"state": "CONFIRMED_GUIDANCE" if micro_confirmed else "WAIT_CONFIRMATION"},
    }


def test_v346_scope_classification_covers_agreed_events():
    assert category_from_title("Non-Farm Employment Change") == "NFP"
    assert category_from_title("Core CPI m/m") == "CPI"
    assert category_from_title("ISM Manufacturing PMI") == "ISM"
    assert category_from_title("FOMC Statement") == "FOMC"
    assert category_from_title("Unemployment Claims") == "JOBLESS_CLAIMS"
    assert category_from_title("FOMC Member Logan Speaks") == "FED_SPEECH"


def test_v346_pre_event_forces_wait_without_predicting_direction():
    now = datetime(2026, 10, 2, 12, 10, tzinfo=UTC)
    event = _event(datetime(2026, 10, 2, 12, 30, tzinfo=UTC))
    bars = _bars(
        datetime(2026, 10, 2, 11, 0, tzinfo=UTC),
        [(100.5, 100.9, 100.2, 100.6)] * 20,
    )
    result = evaluate_news_zone(
        sd_evaluation=_sd(False),
        events=[event],
        bars_m5=bars,
        bars_m15=[],
        now=now,
        source_status={"BLS_OFFICIAL_ICS": "OK:1"},
    )
    assert result["risk_state"] == "PRE_EVENT"
    assert result["state"] == "WAIT_EVENT_VOLATILITY"
    assert result["effective_entry_state"] == "WAIT_FOR_NEWS"
    assert result["policy"]["news_direction_prediction"] is False
    assert result["execution_authority"] is False


def test_v346_post_event_sweep_reclaim_and_micro_confirmation():
    event_at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    rows = [
        (100.5, 100.8, 100.1, 100.4),
        (100.4, 100.6, 99.7, 100.2),
        (100.2, 101.0, 100.1, 100.9),
        (100.9, 101.4, 100.7, 101.2),
    ]
    bars = _bars(event_at - timedelta(minutes=5), rows)
    result = evaluate_news_zone(
        sd_evaluation=_sd(True),
        events=[_event(event_at)],
        bars_m5=bars,
        bars_m15=[],
        now=event_at + timedelta(minutes=25),
        source_status={"BLS_OFFICIAL_ICS": "OK:1"},
    )
    assert result["risk_state"] == "POST_EVENT_DISCOVERY"
    assert result["zone_interaction"]["state"] == "NEWS_SWEEP_REVERSAL_CONFIRMED"
    assert result["state"] == "POST_NEWS_REVERSAL_CONFIRMED"


def test_v346_strong_close_failure_routes_to_next_htf_zone():
    event_at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    rows = [
        (100.4, 100.6, 99.6, 99.7),
        (99.7, 99.9, 99.2, 99.4),
        (99.4, 99.6, 99.0, 99.3),
    ]
    bars = _bars(event_at, rows)
    result = evaluate_news_zone(
        sd_evaluation=_sd(False),
        events=[_event(event_at)],
        bars_m5=bars,
        bars_m15=[],
        now=event_at + timedelta(minutes=20),
        source_status={"BLS_OFFICIAL_ICS": "OK:1"},
    )
    assert result["zone_interaction"]["state"] == "ZONE_FAILED_AFTER_NEWS"
    assert result["state"] == "ZONE_FAILED_SEARCH_NEXT_HTF"
    assert result["next_same_type_htf_zone"]["zone_id"] == "d2"
    assert result["effective_entry_state"] == "BLOCK_FAILED_ZONE"


def test_v346_missing_calendar_is_not_treated_as_clear():
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    bars = _bars(now - timedelta(hours=1), [(100.5, 100.8, 100.2, 100.5)] * 20)
    result = evaluate_news_zone(
        sd_evaluation=_sd(False),
        events=[],
        bars_m5=bars,
        bars_m15=[],
        now=now,
        source_status={"FOREX_FACTORY_WEEKLY": "ERROR:Timeout"},
    )
    assert result["risk_state"] == "NEWS_SOURCE_UNAVAILABLE"
    assert result["state"] == "WAIT_NEWS_DATA"
    assert result["effective_entry_state"] == "WAIT_NEWS_DATA"

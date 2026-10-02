import json
from datetime import UTC, datetime, timedelta

from fx_scanner.xau_intraday_yield_v367 import (
    evaluate_post_event_yield_reversal,
    parse_yahoo_tnx_chart,
    select_latest_post_release_event,
)


def _point(at, value):
    return {"observed_at": at, "yield_pct": value}


def test_v367_parse_yahoo_tnx_chart_extracts_intraday_yield():
    at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    body = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [
                            int(at.timestamp()),
                            int((at + timedelta(minutes=1)).timestamp()),
                        ],
                        "indicators": {
                            "quote": [
                                {"close": [5.24, 5.22]}
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode()
    rows = parse_yahoo_tnx_chart(body)
    assert len(rows) == 2
    assert rows[0]["yield_pct"] == 5.24
    assert rows[1]["yield_pct"] == 5.22


def test_v367_detects_post_nfp_yield_reversal_up_as_gold_headwind():
    event_at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    now = datetime(2026, 10, 2, 14, 30, tzinfo=UTC)
    points = [
        _point(event_at, 5.240),
        _point(event_at + timedelta(minutes=5), 5.200),
        _point(event_at + timedelta(minutes=15), 5.175),
        _point(event_at + timedelta(minutes=60), 5.220),
        _point(now, 5.250),
    ]
    out = evaluate_post_event_yield_reversal(
        points,
        event={
            "title": "Employment Situation",
            "category": "EMPLOYMENT",
            "scheduled_at": event_at.isoformat(),
            "actual": 29_000.0,
            "gold_bias": "GOLD_BULLISH",
        },
        now=now,
    )
    assert out["available"] is True
    assert out["state"] == "YIELD_REVERSAL_UP_STRONG"
    assert out["gold_implication"] == "GOLD_HEADWIND_CONFIRMED"
    assert round(out["initial_drop_bps"], 1) == -6.5
    assert round(out["rebound_from_low_bps"], 1) == 7.5
    assert round(out["net_from_release_bps"], 1) == 1.0


def test_v367_selects_latest_post_release_actual_not_future_focal_event():
    now = datetime(2026, 10, 2, 14, 30, tzinfo=UTC)
    context = {
        "focal_event": {
            "title": "Future event",
            "scheduled_at": (now + timedelta(hours=2)).isoformat(),
            "forecast": 1.0,
        },
        "upcoming_events": [
            {
                "title": "Employment Situation",
                "category": "EMPLOYMENT",
                "scheduled_at": datetime(2026, 10, 2, 12, 30, tzinfo=UTC).isoformat(),
                "actual": 29_000.0,
                "forecast": 90_000.0,
                "gold_bias": "GOLD_BULLISH",
                "gold_bias_confidence": "POST_RELEASE",
            },
            {
                "title": "Unemployment Rate",
                "category": "UNEMPLOYMENT_RATE",
                "scheduled_at": datetime(2026, 10, 2, 12, 30, tzinfo=UTC).isoformat(),
                "actual": 4.2,
                "forecast": 4.1,
                "gold_bias": "GOLD_BULLISH",
                "gold_bias_confidence": "POST_RELEASE",
            },
        ],
    }
    selected = select_latest_post_release_event(context, now=now)
    assert selected is not None
    assert selected["category"] == "EMPLOYMENT"


def test_v367_stale_intraday_yield_fails_closed():
    event_at = datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    now = datetime(2026, 10, 2, 14, 30, tzinfo=UTC)
    out = evaluate_post_event_yield_reversal(
        [
            _point(event_at, 5.24),
            _point(event_at + timedelta(minutes=10), 5.18),
            _point(event_at + timedelta(minutes=30), 5.20),
        ],
        event={
            "title": "Employment Situation",
            "scheduled_at": event_at.isoformat(),
        },
        now=now,
        max_age_seconds=600,
    )
    assert out["available"] is False
    assert out["state"] == "INTRADAY_YIELD_STALE"
    assert out["execution_authority"] is False

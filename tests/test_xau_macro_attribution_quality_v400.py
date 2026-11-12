"""Evidence-quality regression: prevent confident XAU bias from unverified data."""
from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.xau_macro_attribution_quality_v400 import evaluate_attribution_quality

NOW = datetime(2026, 11, 12, 14, 28, tzinfo=UTC)


def _evaluation(usd=.308, us2y=5.0, us10y=2.0, real=3.0):
    out = {
        "macro_score": -55.02,
        "components": {},
    }
    for name, delta in {
        "USD_BROAD_PROXY": usd,
        "US2Y": us2y,
        "US10Y": us10y,
        "REAL_YIELD_10Y": real,
    }.items():
        # Nominal USD H.10 can be days behind a live market.
        obs = NOW - timedelta(days=3 if name == "USD_BROAD_PROXY" else 1)
        out["components"][name] = {
            "delta": delta, "freshness": "FRESH",
            "observed_at": obs.isoformat(),
        }
    return out


def _intraday(*, side="BEARISH_XAU", eligible=True):
    impulse = ("GOLD_HEADWIND" if side == "BEARISH_XAU" else "GOLD_SUPPORT")
    return {
        "intraday_macro_bias": side,
        "confirmation_eligible": eligible,
        "fresh_components": ["DXY", "US10Y_INTRADAY"] if eligible else ["DXY"],
        "components": {
            name: {
                "available": True, "current_at": NOW.isoformat(),
                "gold_implication": impulse,
            }
            for name in ("DXY", "US10Y_INTRADAY")
        },
    }


def _claim(component, actual, forecast, *, sources=1, official=False):
    quotes = [
        {"source": "SHOWMYTRADES", "actual": actual},
    ]
    if sources >= 2:
        quotes.append({"source": "HELIOUS", "actual": actual})
    return {
        "event_component": component,
        "title": component, "category": "JOBLESS_CLAIMS",
        "actual": actual, "forecast": forecast,
        "scheduled_at": (NOW - timedelta(minutes=5)).isoformat(),
        "source_tier": "OFFICIAL_ACTUAL_DOL" if official else "SECONDARY_CONSENSUS_FUSED",
        "actual_quotes": quotes, "actual_source_count": sources,
    }


def test_unverified_actual_does_not_distort_daily_macro():
    events = {"upcoming_events": [
        _claim("INITIAL_JOBLESS_CLAIMS", 200000, 195000, sources=1),
        _claim("CONTINUING_JOBLESS_CLAIMS", 1697000, 1720000, sources=1),
    ]}
    q = evaluate_attribution_quality(
        _evaluation(), event_context=events,
        intraday_confirmation=_intraday(side="BULLISH_XAU"), now=NOW,
    )
    assert q["event_quality"]["state"] == "ACTUAL_NOT_CORROBORATED"
    assert q["event_quality"]["score"] is None
    assert q["legacy_macro_score"] == -55.02
    assert q["quality_screened_score"] == pytest.approx(-51.28, abs=.03)
    assert q["quality_screened_bias"] == "BEARISH_XAU"
    assert q["quality_state"] == "WAIT_MACRO_DIVERGENCE"
    assert q["confidence"] == "LOW"
    assert q["calibrated_accuracy"] is None
    assert not q["execution_authority"] and not q["entry_permission"]


def test_verified_but_opposing_simultaneous_news_is_mixed():
    events = {"upcoming_events": [
        _claim("INITIAL_JOBLESS_CLAIMS", 200000, 195000, sources=2),
        _claim("CONTINUING_JOBLESS_CLAIMS", 1697000, 1720000, sources=2),
    ]}
    q = evaluate_attribution_quality(
        _evaluation(), event_context=events,
        intraday_confirmation=_intraday(), now=NOW,
    )
    assert q["event_quality"]["state"] == "MIXED_SURPRISE"
    assert q["event_quality"]["score"] is None
    assert q["quality_screened_score"] == pytest.approx(-51.28, abs=.03)


def test_verified_hot_news_can_be_counted_without_duplicating_sources():
    event = _claim("INITIAL_JOBLESS_CLAIMS", 188000, 195000, sources=2)
    q = evaluate_attribution_quality(
        _evaluation(), event_context={"upcoming_events": [event, event]},
        intraday_confirmation=_intraday(), now=NOW,
    )
    assert q["event_quality"]["state"] == "VERIFIED_HOT"
    assert q["event_quality"]["score"] == -70
    assert q["event_quality"]["component_count"] == 1
    assert q["quality_screened_score"] < -51.28


def test_one_source_official_actual_passes_verification():
    q = evaluate_attribution_quality(
        _evaluation(),
        event_context={"upcoming_events": [
            _claim("INITIAL_JOBLESS_CLAIMS", 200000, 195000, official=True),
        ]}, intraday_confirmation=_intraday(side="BULLISH_XAU"), now=NOW,
    )
    assert q["event_quality"]["state"] == "VERIFIED_COOL"


def test_fred_stale_timestamp_does_not_get_refreshed_by_worker_heartbeat():
    old = _evaluation()
    old["components"]["USD_BROAD_PROXY"]["observed_at"] = (
        NOW - timedelta(days=8)).isoformat()
    q = evaluate_attribution_quality(
        old, intraday_confirmation=_intraday(), now=NOW,
    )
    assert "USD_BROAD_PROXY" in q["excluded_daily_components"]
    assert q["independent_families"] == 1
    assert q["quality_state"] == "WAIT_DAILY_DATA"


def test_missing_or_future_date_never_counts_as_fresh():
    for wrong in (None, "2040-01-01T00:00:00+00:00", "2026-11-12"):
        e = _evaluation()
        e["components"]["US2Y"]["observed_at"] = wrong
        q = evaluate_attribution_quality(
            e, intraday_confirmation=_intraday(), now=NOW,
        )
        assert "US2Y" in q["excluded_daily_components"]


def test_daily_bearish_with_intraday_support_demands_wait():
    q = evaluate_attribution_quality(
        _evaluation(), intraday_confirmation=_intraday(side="BULLISH_XAU"),
        now=NOW,
    )
    assert q["quality_state"] == "WAIT_MACRO_DIVERGENCE"
    q2 = evaluate_attribution_quality(
        _evaluation(), intraday_confirmation=_intraday(side="BEARISH_XAU"),
        now=NOW,
    )
    # Weekend/delayed daily releases remain labelled daily, never fresh ticks.
    assert q2["quality_state"] == "ALIGNED_CONTEXT_ONLY"
    assert "USD_BROAD_PROXY" in q2["delayed_daily_components"]
    assert q2["confidence"] == "LOW"


def test_no_intraday_confirmation_cannot_be_promoted():
    q = evaluate_attribution_quality(
        _evaluation(), intraday_confirmation=_intraday(eligible=False), now=NOW,
    )
    assert q["quality_state"] == "WAIT_INTRADAY_CONFIRMATION"
    assert q["entry_permission"] is False


def test_future_or_hour_old_release_does_not_pollute_regime_score():
    for minutes in (-1, 70):
        event = _claim("INITIAL_JOBLESS_CLAIMS", 188000, 195000, sources=2)
        event["scheduled_at"] = (NOW - timedelta(minutes=minutes)).isoformat()
        q = evaluate_attribution_quality(
            _evaluation(), event_context={"upcoming_events": [event]},
            intraday_confirmation=_intraday(), now=NOW,
        )
        assert q["event_quality"]["score"] is None


def test_missing_data_and_naive_now_fail_closed():
    q = evaluate_attribution_quality(
        {"macro_score": None, "components": {}}, now=NOW,
    )
    assert q["quality_state"] == "WAIT_DAILY_DATA"
    assert q["quality_screened_score"] is None
    assert q["execution_influence"] is False
    with pytest.raises(ValueError):
        evaluate_attribution_quality({}, now=NOW.replace(tzinfo=None))


def test_stale_intraday_timestamp_rejects_heartbeat_fresh_label():
    intraday = _intraday()
    intraday["components"]["DXY"]["current_at"] = (
        NOW - timedelta(minutes=20)).isoformat()
    q = evaluate_attribution_quality(
        _evaluation(), intraday_confirmation=intraday, now=NOW,
    )
    assert "DXY" not in q["fresh_intraday_components"]
    assert q["quality_state"] == "WAIT_INTRADAY_CONFIRMATION"
    assert q["intraday_confirmation_eligible"] is False

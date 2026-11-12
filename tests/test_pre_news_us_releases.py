"""Regression tests for USD labour/housing news coverage (read-only)."""
from datetime import UTC, datetime, timedelta

from fx_scanner.pre_news_expectation import (
    EVENT_WORKER, MACRO_WORKER, evaluate_pre_news,
)
from fx_scanner.pre_news_entry_guidance import evaluate_entry_guidance
from fx_scanner.pre_news_source_fusion import (
    SourceQuote, canonical_event_key, group_and_fuse,
)

NOW = datetime(2026, 11, 12, 11, 30, tzinfo=UTC)
AT = NOW + timedelta(hours=2)


def _event(title, category, source, forecast, previous, *, at=AT):
    return {
        "title": title, "category": category, "source": source,
        "event_component": title.upper().replace(" ", "_"),
        "scheduled_at": at.isoformat(), "forecast": forecast,
        "previous": previous, "actual": None,
        "source_tier": "SECONDARY_CONSENSUS",
        "forecast_quotes": [
            {"source": source, "forecast": forecast, "previous": previous},
        ],
        "forecast_source_count": 1,
    }


def _snapshot(events, *, now=NOW):
    macro = {
        "macro_score": -45.0,
        "components": {
            name: {
                "observed_at": (now - timedelta(days=1)).isoformat(),
                "freshness": "FRESH", "delta": 4, "provider": "FRED",
            }
            for name in ("US2Y", "US10Y", "REAL_YIELD_10Y")
        },
        "dxy_intraday": {
            "current_at": now.isoformat(), "freshness": "FRESH",
            "available": True, "net_pct": .2, "source": "DXY_PROXY",
        },
        "intraday_yield_context": {
            "current_at": now.isoformat(), "freshness": "FRESH",
            "available": True, "net_bps": 4,
            "state": "US10Y_CASH_LIVE",
        },
    }
    return {
        "published_at": now.isoformat(),
        "heartbeats": [
            {"worker_name": EVENT_WORKER, "observed_at": now.isoformat(),
             "healthy": True,
             "details": {"risk": {
                 "state": "PRE_EVENT_BLOCK", "upcoming_events": events,
                 "focal_event": events[0] if events else {},
             }}},
            {"worker_name": MACRO_WORKER, "observed_at": now.isoformat(),
             "healthy": True, "details": {"evaluation": macro}},
        ],
    }


def test_aliases_and_independent_numeric_forecasts():
    assert canonical_event_key("Initial Jobless Claims") == "INITIAL_JOBLESS_CLAIMS"
    assert canonical_event_key("Unemployment Claims") == "INITIAL_JOBLESS_CLAIMS"
    assert canonical_event_key("Continuing Jobless Claims") == "CONTINUING_JOBLESS_CLAIMS"
    assert canonical_event_key("Existing Home Sales") == "EXISTING_HOME_SALES"
    assert canonical_event_key("Existing Home Sales Change MoM") == "EXISTING_HOME_SALES_CHANGE_MOM"

    quotes = [
        SourceQuote("SHOWMYTRADES", "Initial Jobless Claims", "USD", AT, 195000, 189000),
        SourceQuote("FOREX_FACTORY_WEEKLY", "Unemployment Claims", "USD", AT, 194000, 189000),
        SourceQuote("SHOWMYTRADES", "Initial Jobless Claims", "USD", AT, 195000, 189000),
    ]
    fused = group_and_fuse(quotes)
    assert len(fused) == 1
    assert fused[0].forecast == 194500
    assert fused[0].forecast_source_count == 2
    assert fused[0].source_agreement == "MULTI_SOURCE_AGREE"


def test_initial_claims_selected_and_not_misclassified_as_validated():
    events = [
        _event("Continuing Jobless Claims", "JOBLESS_CLAIMS",
               "SHOWMYTRADES", 1720000, 1718000),
        _event("Initial Jobless Claims", "JOBLESS_CLAIMS",
               "SHOWMYTRADES", 195000, 189000),
        _event("Unemployment Claims", "JOBLESS_CLAIMS",
               "FOREX_FACTORY_WEEKLY", 194000, 189000),
    ]
    view = evaluate_pre_news(_snapshot(events), now=NOW)
    assert view["event"]["event_component"] == "INITIAL_JOBLESS_CLAIMS"
    claims = [r for r in view["event_cluster"]
              if r["event_component"] == "INITIAL_JOBLESS_CLAIMS"]
    assert len(claims) == 1
    assert claims[0]["forecast"] == 194500
    assert claims[0]["forecast_pair_count"] == 2
    assert not view["forecast_quorum_met"]
    assert view["scenarios"][0]["Implikasi awal XAU"] == "Cenderung mendukung"


def test_housing_supported_but_unrelated_other_usd_not_inferred():
    home = _event("Existing Home Sales", "OTHER_USD", "SHOWMYTRADES",
                  3850000, 3990000)
    view = evaluate_pre_news(_snapshot([home]), now=NOW)
    assert view["event"]["event_component"] == "EXISTING_HOME_SALES"
    assert view["event_cluster"][0]["forecast"] == 3850000
    assert not view["forecast_quorum_met"]
    other = _event("Crude Oil Inventories", "OTHER_USD", "SHOWMYTRADES", -600, -900)
    not_supported = evaluate_pre_news(_snapshot([other]), now=NOW)
    assert not_supported["event"] is None


def test_macro_bias_is_separate_from_jobless_surprise():
    event = _event("Initial Jobless Claims", "JOBLESS_CLAIMS",
                   "SHOWMYTRADES", 195000, 189000)
    snap = _snapshot([event])
    view = evaluate_pre_news(snap, now=NOW)
    guidance = evaluate_entry_guidance(view, snap, now=NOW)
    assert guidance["decision"] == "SELL BIAS — TUNGGU RILIS"
    assert guidance["forecast_verified"] is False
    assert guidance["news_verified"] is False
    assert guidance["trade_ready"] is False
    assert guidance["release_triggers"][0]["hot_if_actual_below"] == 195000
    assert guidance["release_triggers"][0]["cool_if_actual_above"] == 195000


def test_post_release_single_source_cannot_offer_trade_setup():
    release = NOW - timedelta(minutes=2)
    event = _event("Existing Home Sales", "OTHER_USD", "SHOWMYTRADES",
                   3850000, 3990000, at=release)
    snap = _snapshot([event])
    view = {
        "state": "POST_NEWS",
        "event": event,
        "event_cluster": [{"event_component": "EXISTING_HOME_SALES",
                           "hawkish_tilt": 1, "actual": 4100000,
                           "forecast": 3850000, "surprise": 250000,
                           "source": "SHOWMYTRADES"}],
        "news_conclusion_status": "PROVISIONAL_ACTUAL_SINGLE_SOURCE",
    }
    guidance = evaluate_entry_guidance(view, snap, now=NOW)
    assert guidance["decision"] == "WAIT — ACTUAL BELUM TERVERIFIKASI"
    assert guidance["trade_ready"] is False
    assert not guidance["execution_authority"]


def test_next_housing_release_replaces_older_claims_after_spike_window():
    claims = _event(
        "Initial Jobless Claims", "JOBLESS_CLAIMS",
        "SHOWMYTRADES", 195000, 189000,
        at=NOW - timedelta(hours=1),
    )
    claims["actual"] = 188000
    claims["source_tier"] = "OFFICIAL_ACTUAL_DOL"
    claims["actual_source_count"] = 1
    claims["actual_quotes"] = [{"source": "SHOWMYTRADES", "actual": 188000}]
    home = _event(
        "Existing Home Sales", "OTHER_USD", "SHOWMYTRADES",
        3850000, 3990000, at=NOW + timedelta(minutes=30),
    )
    data = _snapshot([claims, home])
    data["heartbeats"][0]["details"]["risk"]["state"] = "POST_EVENT_DISCOVERY"
    view = evaluate_pre_news(data, now=NOW)
    assert view["event"]["event_component"] == "EXISTING_HOME_SALES"
    assert view["minutes_to_event"] == 30

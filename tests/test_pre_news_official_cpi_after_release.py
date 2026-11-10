"""Post-release CPI news truth must not be confused with pre-release forecasts."""
from datetime import UTC, datetime, timedelta

from fx_scanner.pre_news_official_cpi import parse_official_cpi_release
from fx_scanner.pre_news_expectation import (
    EVENT_WORKER, MACRO_WORKER, evaluate_pre_news,
)

RELEASE = datetime(2026, 11, 10, 13, 30, tzinfo=UTC)
NOW = RELEASE + timedelta(minutes=10)
BLS_BODY = """
Transmission of material in this release is embargoed until
8:30 a.m. (ET) Tuesday, November 10, 2026 USDL-26-1685
CONSUMER PRICE INDEX - OCTOBER 2026
The Consumer Price Index for All Urban Consumers (CPI-U) increased
0.4 percent on a seasonally adjusted basis in October after rising 0.6 percent in September.
The index for all items less food and energy rose 0.3 percent in October, as it did in September.
"""


def _event(component, forecast, previous, actual, official=True):
    return {
        "title": component.replace("_", " "),
        "event_component": component,
        "category": "CPI",
        "currency": "USD",
        "scheduled_at": RELEASE.isoformat(),
        "actual": actual, "forecast": forecast, "previous": previous,
        "source": "BLS_OFFICIAL_CPI_RELEASE" if official else "INVESTING_COM",
        "source_tier": (
            "OFFICIAL_ACTUAL_WITH_FUSED_CONSENSUS" if official
            else "SECONDARY_CONSENSUS"
        ),
    }


def _snapshot(actuals=True, official=True):
    headline = _event("CPI_MOM", .3, .6, .4 if actuals else None, official)
    core = _event("CORE_CPI_MOM", .2, .3, .3 if actuals else None, official)
    return {"heartbeats": [
        {"worker_name": EVENT_WORKER, "observed_at": NOW.isoformat(),
         "healthy": True, "details": {"risk": {
             "upcoming_events": [headline, core],
             "latest_released_event": headline,
             "state": "EVENT_WINDOW",
         }}},
        {"worker_name": MACRO_WORKER, "observed_at": NOW.isoformat(),
         "healthy": True, "details": {"evaluation": {}}},
    ]}


def test_bls_cpi_parser_uses_official_date_and_monthly_actuals():
    result = parse_official_cpi_release(BLS_BODY, now=NOW)
    assert result["CPI_MOM"] == .4
    assert result["CORE_CPI_MOM"] == .3
    assert result["release_at"] == RELEASE
    assert "CPI_YOY" not in result
    assert parse_official_cpi_release(BLS_BODY, now=RELEASE-timedelta(seconds=1)) == {}
    assert parse_official_cpi_release(BLS_BODY, now=NOW+timedelta(days=2)) == {}


def test_hot_actual_overrides_cool_forecast_after_release():
    data = _snapshot()
    view = evaluate_pre_news(data, now=NOW)
    assert view["state"] == "POST_NEWS"
    assert view["news_conclusion_status"] == "OFFICIAL_VERIFIED"
    assert view["news_conclusion"] == "HOT SURPRISE — BEARISH XAU"
    assert view["xau_bias"] == "BEARISH_XAU"
    assert len(view["event_cluster"]) == 2
    assert {row["surprise"] for row in view["event_cluster"]} == {0.1}
    assert not view["execution_authority"]
    assert not view["execution_influence"]


def test_secondary_actual_never_impersonates_official():
    view = evaluate_pre_news(_snapshot(official=False), now=NOW)
    assert view["state"] == "POST_NEWS_PENDING"
    assert view["news_conclusion_status"] == "WAITING_ACTUAL"
    assert view["xau_bias"] == "UNAVAILABLE"
    assert "BULLISH" not in view["news_conclusion"]


def test_unreleased_or_stale_actual_not_used():
    data = _snapshot()
    before = RELEASE - timedelta(minutes=5)
    data["heartbeats"][0]["observed_at"] = before.isoformat()
    data["heartbeats"][1]["observed_at"] = before.isoformat()
    view = evaluate_pre_news(data, now=before)
    assert view["state"] != "POST_NEWS"
    assert view["news_conclusion"] != "HOT SURPRISE — BEARISH XAU"

    stale = _snapshot()
    stale["heartbeats"][0]["observed_at"] = (NOW-timedelta(minutes=11)).isoformat()
    view = evaluate_pre_news(stale, now=NOW)
    assert view["news_conclusion_status"] == "STALE"
    assert view["xau_bias"] == "UNAVAILABLE"


def test_missing_core_actual_is_explicitly_partial():
    data = _snapshot()
    data["heartbeats"][0]["details"]["risk"]["upcoming_events"][1]["actual"] = None
    result = evaluate_pre_news(data, now=NOW)
    assert result["news_conclusion_status"] == "PARTIAL_ACTUAL"
    assert result["xau_bias"] == "UNAVAILABLE"
    assert "ACTUAL PARSIAL" in result["news_conclusion"]


def test_no_actual_after_release_is_not_false_cool_bullish_signal():
    result = evaluate_pre_news(_snapshot(actuals=False), now=NOW)
    assert result["news_conclusion_status"] == "WAITING_ACTUAL"
    assert result["xau_bias"] == "UNAVAILABLE"

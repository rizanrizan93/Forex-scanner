"""Regression: directional news preparation must be causal and explainable."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.pre_news_entry_guidance import evaluate_entry_guidance
from fx_scanner.pre_news_expectation import EVENT_WORKER, MACRO_WORKER

RELEASE = datetime(2026, 11, 13, 13, 30, tzinfo=UTC)
BEFORE = RELEASE - timedelta(minutes=20)
AFTER = RELEASE + timedelta(minutes=2)


def fixture(now, *, dxy=.22, yield_bps=4.0, macro=-40.0, category="PPI"):
    event = {
        "title": "Core PPI m/m", "category": category,
        "scheduled_at": RELEASE.isoformat(),
    }
    state = "PRE_NEWS" if now < RELEASE else "POST_NEWS"
    view = {
        "state": state, "event": event, "forecast_quorum_met": True,
        "news_conclusion_status": "OFFICIAL_VERIFIED",
        "event_cluster": [
            {"event_component": "PPI_MOM", "hawkish_tilt": 1,
             "actual": .5, "forecast": .4, "surprise": .1, "source": "BLS"},
            {"event_component": "CORE_PPI_MOM", "hawkish_tilt": 1,
             "actual": .4, "forecast": .3, "surprise": .1, "source": "BLS"},
        ],
    }
    snapshot = {
        "published_at": now.isoformat(),
        "heartbeats": [
            {"worker_name": EVENT_WORKER, "healthy": True,
             "observed_at": now.isoformat(), "details": {}},
            {"worker_name": MACRO_WORKER, "healthy": True,
             "observed_at": now.isoformat(), "details": {"evaluation": {
                 "macro_score": macro,
                 "dxy_intraday": {"current_at": now.isoformat(),
                     "available": True, "freshness": "FRESH", "net_pct": dxy},
                 "intraday_yield_context": {
                     "current_at": now.isoformat(), "available": True,
                     "freshness": "FRESH", "net_bps": yield_bps,
                     "state": "US10Y_CASH_LIVE",
                 },
             }}},
        ],
    }
    return view, snapshot


def test_forecast_cooling_does_not_force_bullish_when_macro_hawkish():
    view, snap = fixture(BEFORE)
    view["forecast_risk"] = "COOL RISK (BULLISH XAU)"
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["decision"] == "SELL BIAS — TUNGGU RILIS"
    assert result["score_xau"] < -35
    assert result["bias"] == "SELL"
    assert result["hot_cool_risk"] == "HOT-RISK MACRO (POTENSI BEARISH XAU)"
    assert len(result["release_triggers"]) == 2
    assert result["release_triggers"][0]["hot_if_actual_at_least"] == .5
    assert result["release_triggers"][1]["cool_if_actual_at_most"] == .2
    assert result["confidence"] == "MODERATE"
    assert not result["trade_ready"] and not result["execution_authority"]
    assert "BELUM diketahui" in result["reason"]


def test_dovish_macro_creates_conditional_buy_bias():
    view, snap = fixture(BEFORE, dxy=-.18, yield_bps=-4, macro=40)
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["decision"].startswith("BUY BIAS")
    assert result["score_xau"] > 35


def test_neutral_macro_abstains_and_forecast_only_not_trade():
    view, snap = fixture(BEFORE, dxy=0.0, yield_bps=0.0, macro=0.0)
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["decision"] == "WAIT"
    assert result["bias"] == "NEUTRAL"


def test_hawkish_macro_without_three_forecasts_is_low_confidence():
    view, snap = fixture(BEFORE)
    view["forecast_quorum_met"] = False
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["bias"] == "SELL"
    assert result["confidence"] == "LOW"
    assert any("Quorum" in warning for warning in result["warnings"])


def test_stale_frozen_or_future_feed_never_issues_bias():
    view, snap = fixture(BEFORE)
    for status in ["stale", "future", "fallback"]:
        other = deepcopy(snap)
        if status == "stale":
            other["published_at"] = (BEFORE-timedelta(minutes=12)).isoformat()
        elif status == "future":
            other["heartbeats"][0]["observed_at"] = (BEFORE+timedelta(seconds=1)).isoformat()
        else:
            other["publication_fresh"] = False
        result = evaluate_entry_guidance(view, other, now=BEFORE)
        assert result["decision"] == "WAIT"
        assert result["score_xau"] is None


def test_fomc_requires_language_not_guess_from_macro():
    view, snap = fixture(BEFORE, category="FOMC")
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["decision"] == "WAIT"


def test_hot_ppi_post_release_means_sell_setup_not_automatic_entry():
    view, snap = fixture(AFTER)
    result = evaluate_entry_guidance(view, snap, now=AFTER)
    assert result["decision"] == "SELL SETUP — KONFIRMASI M1/M5"
    assert result["news_verified"] is True
    assert result["hot_cool_risk"] == "HOT SURPRISE ACTUAL"
    assert result["confidence"] == "MODERATE"
    assert result["trade_ready"] is False
    assert result["execution_influence"] is False
    assert any("4 menit" in note for note in result["warnings"])


def test_post_release_macro_conflict_requires_wait():
    view, snap = fixture(AFTER, dxy=-.20, yield_bps=-4, macro=45)
    result = evaluate_entry_guidance(view, snap, now=AFTER)
    assert result["decision"] == "WAIT — NEWS vs MAKRO KONFLIK"


@pytest.mark.parametrize("status", ["PARTIAL_ACTUAL", "WAITING_ACTUAL"])
def test_post_missing_actual_does_not_reuse_pre_forecast(status):
    view, snap = fixture(AFTER)
    view["news_conclusion_status"] = status
    if status == "WAITING_ACTUAL":
        view["state"] = "POST_NEWS_PENDING"
    result = evaluate_entry_guidance(view, snap, now=AFTER)
    assert result["decision"] == "WAIT"
    assert result["news_verified"] is False


def test_news_spike_entry_window_expires_after_ten_minutes():
    later = RELEASE + timedelta(minutes=11)
    view, snap = fixture(later)
    result = evaluate_entry_guidance(view, snap, now=later)
    assert result["decision"] == "WAIT — JENDELA SPIKE NEWS SELESAI"
    assert result["bias"] == "SELL"
    assert result["trade_ready"] is False


def test_intraday_quotes_older_than_three_minutes_are_context_not_confirmation():
    view, snap = fixture(BEFORE)
    age = (BEFORE - timedelta(minutes=6)).isoformat()
    macro = snap["heartbeats"][1]["details"]["evaluation"]
    macro["dxy_intraday"]["current_at"] = age
    macro["intraday_yield_context"]["current_at"] = age
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["bias"] == "SELL"
    assert result["macro_confirmed"] is False
    assert result["confidence"] == "LOW"


def test_no_lookahead_at_same_instant_as_release():
    view, snap = fixture(BEFORE)
    view["state"] = "POST_NEWS"
    result = evaluate_entry_guidance(view, snap, now=BEFORE)
    assert result["decision"] == "WAIT"

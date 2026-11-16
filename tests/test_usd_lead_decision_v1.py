from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fx_scanner.usd_lead_decision_v1 import (
    CONTRACT, EXECUTION_AUTHORITY, SPREAD_CONTRACT, evaluate_usd_lead,
)


NOW = datetime(2026, 11, 16, 2, 0, tzinfo=UTC)


def at(delta_minutes=0):
    return (NOW - timedelta(minutes=delta_minutes)).isoformat()


def daily(name, current, previous, delta):
    return {
        "provider": "US_TREASURY_DAILY_XML",
        "freshness": "FRESH",
        "release_state": "CURRENT_PUBLISHED",
        "current": current, "previous": previous, "delta": delta,
        "observed_at": "2026-11-13T00:00:00+00:00",
        "previous_observed_at": "2026-11-12T00:00:00+00:00",
    }


def snapshot():
    return {
        "fed_funds_futures": {
            "source": "YAHOO_FINANCE_ZQ_FRONT_PROXY", "available": True,
            "current": 96.80, "reference": 96.82,
            "current_at": at(2), "reference_at": at(62),
            "implied_rate_change_bps": 2.0,
        },
        "dxy_intraday": {
            "source": "YAHOO_FINANCE_ICE_DXY_PROXY", "available": True,
            "current": 103.15, "reference": 103.0,
            "current_at": at(2), "reference_at": at(62),
            "net_pct": (103.15 / 103 - 1) * 100,
        },
        "components": {
            "US2Y": daily("US2Y", 4.90, 4.86, 4),
            "REAL_YIELD_10Y": daily("REAL_YIELD_10Y", 2.70, 2.65, 5),
        },
        "attribution_quality": {
            "event_quality": {"state": "VERIFIED_HOT", "event_time": at(20)},
        },
    }


def spread():
    return {
        "contract": SPREAD_CONTRACT,
        "source": "US_TREASURY_AND_BUNDESBANK_OFFICIAL_DAILY",
        "observed_at": "2026-11-13T00:00:00+00:00",
        "previous_observed_at": "2026-11-12T00:00:00+00:00",
        "us2y_current": 4.90, "us2y_previous": 4.86,
        "de2y_current": 2.0, "de2y_previous": 1.99,
        "execution_authority": False, "execution_influence": False,
    }


def xau_checklist():
    return {
        "SELL": {
            "items": [
                {"key": k, "state": "PASS"} for k in ("h1", "m15", "m5", "v404")
            ]
        },
        "BUY": {
            "items": [
                {"key": k, "state": "FAIL"} for k in ("h1", "m15", "m5", "v404")
            ]
        },
    }


def test_full_usd_up_xau_sell_shadow_only():
    x = evaluate_usd_lead(snapshot(), spread=spread(),
                          xau_checklist=xau_checklist(), now=NOW)
    assert x["contract"] == CONTRACT
    assert EXECUTION_AUTHORITY is False
    assert x["usd_up"]["status"] == "XAU_SELL_SHADOW_WATCH"
    assert x["usd_up"]["passed"] == 7
    assert x["usd_down"]["status"] == "WAIT"
    assert x["execution_authority"] is False


def test_no_macro_info_never_predicts_usd_direction():
    x = evaluate_usd_lead({}, now=NOW)
    assert x["usd_up"]["unknown"] == 7
    assert x["usd_up"]["status"] == "WAIT"
    assert x["usd_direction"] == "WAIT"


def test_fed_proxy_derived_from_us2y_is_not_zq():
    d = snapshot()
    d["fed_funds_futures"] = {
        "state": "HAWKISH_REPRICING_PROXY", "delta_bps": 8.0,
        "source": "US2Y_DAILY_DELTA_PROXY_NOT_FED_FUNDS_FUTURES",
    }
    x = evaluate_usd_lead(d, spread=spread(),
                          xau_checklist=xau_checklist(), now=NOW)
    assert x["usd_up"]["rows"][0]["state"] == "UNKNOWN"
    assert x["usd_up"]["status"] == "USD_DAILY_RATES_WATCH_ONLY"
    assert x["execution_authority"] is False


def test_stale_fed_quote_rejected_even_if_heartbeat_was_fresh():
    d = snapshot()
    d["fed_funds_futures"]["current_at"] = at(91)
    x = evaluate_usd_lead(d, spread=spread(), now=NOW)
    assert x["usd_up"]["rows"][0]["state"] == "UNKNOWN"
    assert x["usd_up"]["status"] != "XAU_SELL_SHADOW_WATCH"


def test_no_bundesbank_daily_spread_is_not_assumed():
    x = evaluate_usd_lead(snapshot(), spread=None, now=NOW)
    assert x["usd_up"]["rows"][2]["state"] == "UNKNOWN"
    assert x["usd_up"]["status"] == "USD_DIRECTION_WATCH_ONLY"


def test_falling_dxy_conflicts_with_hawkish_fed():
    d = snapshot()
    d["dxy_intraday"]["current"] = 102.9
    d["dxy_intraday"]["net_pct"] = (102.9/103.0 - 1) * 100
    x = evaluate_usd_lead(d, spread=spread(),
                          xau_checklist=xau_checklist(), now=NOW)
    assert x["usd_up"]["rows"][3]["state"] == "FAIL"
    assert x["usd_up"]["status"] == "WAIT"


def test_daily_yield_noncurrent_release_rejected():
    d = snapshot()
    d["components"]["US2Y"]["release_state"] = "RELEASE_PENDING"
    d["components"]["REAL_YIELD_10Y"]["release_state"] = "DAILY_DELAYED"
    x = evaluate_usd_lead(d, spread=spread(), now=NOW)
    assert x["usd_up"]["rows"][1]["state"] == "UNKNOWN"
    assert x["usd_up"]["rows"][4]["state"] == "UNKNOWN"


def test_early_morning_fresh_quote_cannot_be_from_future():
    d = snapshot()
    d["dxy_intraday"]["current_at"] = (NOW + timedelta(minutes=5)).isoformat()
    x = evaluate_usd_lead(d, now=NOW)
    assert x["usd_up"]["rows"][3]["state"] == "UNKNOWN"


def test_news_no_actual_does_not_create_vote():
    d = snapshot()
    d["attribution_quality"]["event_quality"] = {
        "state": "NO_VERIFIED_RECENT_ACTUAL", "event_time": None
    }
    x = evaluate_usd_lead(d, spread=spread(),
                          xau_checklist=xau_checklist(), now=NOW)
    assert x["usd_up"]["rows"][5]["state"] == "UNKNOWN"
    assert x["usd_up"]["status"] == "XAU_SELL_SHADOW_WATCH"


def test_xau_technical_unknown_blocks_full_watch():
    x = evaluate_usd_lead(snapshot(), spread=spread(),
                          xau_checklist={"SELL": {"items": [
                              {"key": k, "state": "UNKNOWN"} for k in
                              ("h1", "m15", "m5", "v404")
                          ]}}, now=NOW)
    assert x["usd_up"]["rows"][6]["state"] == "UNKNOWN"
    assert x["usd_up"]["status"] == "USD_DIRECTION_WATCH_ONLY"


def test_daily_yield_delta_inconsistent_with_prices_rejected():
    d = snapshot()
    d["components"]["US2Y"]["delta"] = 10_000
    x = evaluate_usd_lead(d, spread=spread(), now=NOW)
    assert x["usd_up"]["rows"][1]["state"] == "UNKNOWN"


def test_no_naive_time_allowed():
    with pytest.raises(ValueError, match="NOW_REQUIRES_TIMEZONE"):
        evaluate_usd_lead({}, now=datetime(2026, 11, 16))

"""R3 4-factor WATCH adapter must abstain rather than invert direction."""
from copy import deepcopy
from research.fed_expectation_r1.four_factor_watch_r3 import four_factor_watch

NOW="2026-11-18T19:06:00Z"
def inputs():
    r1={
        "event_id":"M1","release_at":"2026-11-18T19:00:00Z",
        "decision_at":"2026-11-18T19:05:00Z",
        "source_quality":"CAPTURED_REALTIME",
        "data_ready":True,"stage":"POST_EVENT_CONFIRMED",
        "fed_repricing_bp":4.0,"us2y_change_bp":2.0,
        "dxy_proxy_return_pct":.2,"search_bias":"SEARCH_SELL_REBOUND",
    }
    ten={
        "event_id":"M1","series":"US10Y_YIELD_BP","unit":"BPS",
        "instrument":"UST10Y_REAL_CASH_YIELD",
        "provider":"TEST_SYNTHETIC_UNIT_FIXTURE",
        "source_url":"https://www.federalreserve.gov/",
        "provenance_mode":"CAPTURED_REALTIME",
        "pre_yield_bp":401,"post_yield_bp":404,
        "pre_available_at":"2026-11-18T18:59:00Z",
        "post_available_at":"2026-11-18T19:04:00Z",
    }
    r2={
        "event_id":"M1","headline_stance":"HAWKISH",
        "macro_watch_bias":"SEARCH_SELL_REBOUND",
        "at":"2026-11-18T19:04:00Z",
    }
    return r1,ten,r2

def test_all_four_hawkish_plus_text_sell_watch_only():
    d=four_factor_watch(*inputs(),decision_at=NOW)
    assert d["direction"]=="SELL"
    assert d["watch_bias"]=="SEARCH_SELL_REBOUND"
    assert d["authority_to_deploy"] is False
    assert d["authority_to_place_order"] is False
    assert d["predicted_probability"] is None
    assert d["research_validation"]=="FAILED_BOTH_SIDES_80PCT_2019_2026"

def test_all_four_dovish_plus_text_buy_watch_only():
    r1,ten,r2=inputs()
    r1.update(fed_repricing_bp=-4,us2y_change_bp=-3,
              dxy_proxy_return_pct=-.2,search_bias="SEARCH_BUY_DIP")
    ten["post_yield_bp"]=398
    r2.update(headline_stance="DOVISH",macro_watch_bias="SEARCH_BUY_DIP")
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="BUY" and out["watch_bias"]=="SEARCH_BUY_DIP"

def test_hawkish_fed_but_dovish_us10y_is_wait():
    r1,ten,r2=inputs()
    ten["post_yield_bp"]=397
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="WAIT"
    assert out["reason_codes"]==["POLICY_YIELDS_USD_CONFLICT_OR_TOO_SMALL"]

def test_dovish_fed_text_disagrees_with_hawkish_market_wait():
    r1,ten,r2=inputs()
    r2["headline_stance"]="DOVISH"
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="WAIT"
    assert out["reason_codes"]==["FED_COMMUNICATION_AND_MARKET_DISAGREE"]

def test_reconstructed_us10y_never_live_watch():
    r1,ten,r2=inputs()
    ten["provenance_mode"]="HISTORICAL_RECONSTRUCTED"
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="WAIT"

def test_wrong_event_id_never_uses_stale_fomc_quote():
    r1,ten,r2=inputs()
    ten["event_id"]="OLDER"
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["reason_codes"]==["SOURCE_EVENT_MISMATCH"]

def test_future_10y_timestamp_fails_closed():
    r1,ten,r2=inputs()
    ten["post_available_at"]="2026-11-18T19:07:00Z"
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="WAIT"
    assert out["reason_codes"]==["FUTURE_OR_STALE_US10Y_SNAPSHOT"]

def test_missing_source_does_not_invent_probability():
    r1,ten,r2=inputs()
    ten["source_url"]="http://unverified.com/"
    out=four_factor_watch(r1,ten,r2,decision_at=NOW)
    assert out["direction"]=="WAIT"
    assert out["predicted_probability"] is None

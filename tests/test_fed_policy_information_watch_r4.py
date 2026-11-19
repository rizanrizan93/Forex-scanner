"""R4 live-watch deterministic tests: SELL+BUY, information veto, PIT."""

from research.fed_expectation_r1.policy_information_watch_r4 import watch
import pytest
EVENT={"event_id":"FOMC_TEST_R4","release_at":"2026-11-18T19:00:00Z",
       "source_url":"https://www.federalreserve.gov/"}
AT="2026-11-18T19:06:00Z"
SPECS={
    "OIS1Y_RATE_BP":("BPS",450.0,453.0),
    "TIPS10Y_INTRADAY_YIELD_BP":("BPS",140.0,142.0),
    "SP500_INDEX_LEVEL":("INDEX_LEVEL",6000.0,5988.0),
    "USD_INDEX_PROXY_LEVEL":("INDEX_LEVEL",100.0,100.2),
}

def points():
    out=[]
    for s,(unit,pre,post) in SPECS.items():
        for is_post,value in ((False,pre),(True,post)):
            when="2026-11-18T19:04:00Z" if is_post else "2026-11-18T18:59:00Z"
            out.append({
                "event_id":EVENT["event_id"],"series":s,
                "unit":unit,"value":value,"instrument":s,
                "provider":"SIMULATED_INTRADAY_FIXTURE",
                "source_url":"https://example.org/quoted-data",
                "provenance_mode":"CAPTURED_REALTIME",
                "quote_frequency":"INTRADAY_CASH_TIPS" if "TIPS" in s else "INTRADAY",
                "bar_end_at":when,"published_at":when,"ingested_at":when,
            })
    return out

def test_hawkish_pure_policy_shock_produces_sell_watch_only():
    x=watch(EVENT,points(),decision_at=AT)
    assert x["direction"]=="SELL"
    assert x["watch_bias"]=="SEARCH_SELL_REBOUND"
    assert x["policy_information_regime"]=="POLICY_LIKE"
    assert x["authority_to_deploy"] is False
    assert x["authority_to_send_orders"] is False
    assert x["predicted_probability"] is None

def test_dovish_pure_policy_shock_produces_buy_watch_only():
    p=points()
    for x in p:
        if x["bar_end_at"].startswith("2026-11-18T19:04"):
            x["value"]={
                "OIS1Y_RATE_BP":447.0,
                "TIPS10Y_INTRADAY_YIELD_BP":138.0,
                "SP500_INDEX_LEVEL":6012.0,
                "USD_INDEX_PROXY_LEVEL":99.8,
            }[x["series"]]
    o=watch(EVENT,p,decision_at=AT)
    assert o["direction"]=="BUY"
    assert o["watch_bias"]=="SEARCH_BUY_DIP"

def test_information_shock_stocks_and_rate_same_direction_wait():
    p=points()
    for x in p:
        if x["series"]=="SP500_INDEX_LEVEL" and x["bar_end_at"].startswith("2026-11-18T19:04"):
            x["value"]=6012
    o=watch(EVENT,p,decision_at=AT)
    assert o["policy_information_regime"]=="INFORMATION_LIKE"
    assert o["direction"]=="WAIT"

def test_real_yield_disagrees_usd_wait():
    p=points()
    for x in p:
        if x["series"]=="TIPS10Y_INTRADAY_YIELD_BP" and x["bar_end_at"].startswith("2026-11-18T19:04"):
            x["value"]=138.0
    o=watch(EVENT,p,decision_at=AT)
    assert o["direction"]=="WAIT"

def test_opposite_fomc_text_veto_without_reinterpreting_actual():
    r2={"event_id":EVENT["event_id"],"at":"2026-11-18T19:03:00Z",
        "headline_stance":"DOVISH"}
    o=watch(EVENT,points(),decision_at=AT,r2_context=r2)
    assert o["direction"]=="WAIT"
    assert o["reason_codes"]==["FOMC_TEXT_VS_MARKET_CONTRADICTION"]

def test_reconstructed_old_event_data_cannot_be_reused_as_live():
    p=points()
    p[0]["provenance_mode"]="HISTORICAL_RECONSTRUCTED"
    with pytest.raises(ValueError,match="EXPOST_OR_UNCAPTURED"):
        watch(EVENT,p,decision_at=AT)

def test_daily_tips_not_admissible_as_intraday():
    p=points()
    p[2]["quote_frequency"]="FRED_DAILY_DGS10"
    with pytest.raises(ValueError,match="DAILY_TIPS"):
        watch(EVENT,p,decision_at=AT)

def test_new_fomc_release_not_known_in_advance():
    o=watch(EVENT,[],decision_at="2026-11-18T18:59:59Z")
    assert o["direction"]=="WAIT"
    assert o["reason_codes"]==["EVENT_NOT_YET_RELEASED"]

def test_wrong_event_id_fails_source_gate():
    p=points();p[0]["event_id"]="OLD_FOMC"
    with pytest.raises(ValueError,match="SNAPSHOT_PROVENANCE"):
        watch(EVENT,p,decision_at=AT)

def test_future_price_ingestion_fails_no_lookahead():
    p=points();p[-1]["ingested_at"]="2026-11-18T19:07:00Z"
    with pytest.raises(ValueError,match="FUTURE_SNAPSHOT_LOOKAHEAD"):
        watch(EVENT,p,decision_at=AT)

def test_expired_event_window_is_wait():
    o=watch(EVENT,points(),decision_at="2026-11-19T01:00:00Z")
    assert o["direction"]=="WAIT"
    assert o["reason_codes"]==["FOMC_EVENT_WINDOW_TOO_OLD"]

def test_missing_tips_source_returns_wait():
    p=[x for x in points() if x["series"]!="TIPS10Y_INTRADAY_YIELD_BP"]
    o=watch(EVENT,p,decision_at=AT)
    assert o["direction"]=="WAIT"
    assert o["reason_codes"]==["MISSING_TIPS10Y_INTRADAY_YIELD_BP"]

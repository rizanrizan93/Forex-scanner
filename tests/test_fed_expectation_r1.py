"""Synthetic PIT tests. Green does not mean validated trading accuracy."""
from datetime import timedelta
import pytest
from research.fed_expectation_r1.engine import (
    decide, EXECUTION_AUTHORITY, EXECUTION_INFLUENCE,
)

RELEASE="2026-11-19T19:00:00Z"
EVENT={"event_id":"FOMC_DEMO_001","event_kind":"FOMC_STATEMENT",
       "release_at":RELEASE,"source_url":"https://www.federalreserve.gov/"}
MAP={"EXPECTED_FED_RATE_BP":("ZQ_DEC27","BPS","CME_FED_FUTURES","DEC_2027"),
     "US2Y_YIELD_BP":("UST2Y","BPS","DIRECT_CASH_YIELD",None),
     "DXY_PROXY_LEVEL":("DUKASCOPY_DOLLARIDXUSD","INDEX_LEVEL","DUKASCOPY",None)}


def point(series,value,time,*,mode="CAPTURED_REALTIME",contract=None,observed=None):
    instrument,unit,provider,default_contract=MAP[series]
    out={"series":series,"instrument":instrument,"unit":unit,"provider":provider,
         "value":value,"bar_end_at":time,"published_at":time,
         "ingested_at":observed or time,"source_url":"https://example.org/market-data",
         "provenance_mode":mode,"is_official_ice_dxy":False}
    if series=="EXPECTED_FED_RATE_BP":
        out["meeting_or_contract"]=contract or default_contract
    return out


def history(bull=False):
    if bull:
        before=(440,430,105.0)
        after=(437,428,104.8)
    else:
        before=(440,430,105.0)
        after=(444,432,105.2)
    pre="2026-11-19T18:59:00Z"
    post="2026-11-19T19:03:00Z"
    return [point(s,b,pre) for s,b in zip(MAP,before)]+[
        point(s,a,post) for s,a in zip(MAP,after)]


def test_hawkish_three_market_repricing_search_sell_only():
    r=decide(EVENT,history(),decision_at="2026-11-19T19:05:00Z")
    assert r["direction"]=="HAWKISH_REPRICING"
    assert r["search_bias"]=="SEARCH_SELL_REBOUND"
    assert r["fed_repricing_bp"]==4
    assert r["data_ready"]
    assert r["execution_authority"] is False
    assert EXECUTION_AUTHORITY is False and EXECUTION_INFLUENCE is False


def test_dovish_three_market_repricing_search_buy_only():
    r=decide(EVENT,history(bull=True),decision_at="2026-11-19T19:05:00Z")
    assert r["direction"]=="DOVISH_REPRICING"
    assert r["search_bias"]=="SEARCH_BUY_DIP"
    assert r["us2y_change_bp"]==-2


def test_before_news_cannot_predict_future_repricing():
    r=decide(EVENT,history(),decision_at="2026-11-19T18:59:59Z")
    assert r["direction"]=="WAIT"
    assert r["fed_repricing_bp"] is None
    assert r["reason_codes"]==["NO_FUTURE_POLICY_SURPRISE_BEFORE_RELEASE"]


def test_future_quote_must_not_enter_early_decision():
    d=history()
    r=decide(EVENT,d,decision_at="2026-11-19T19:01:00Z")
    assert r["direction"]=="WAIT"
    assert any("NO_POST_EVENT_" in c for c in r["reason_codes"])


def test_conflicting_yield_versus_fed_is_wait():
    d=history()
    d[-2]["value"]=428
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["direction"]=="WAIT"
    assert r["data_ready"] is True
    assert "MACRO_SIGN_NOT_UNANIMOUS" in r["reason_codes"]


def test_no_intraday_2y_yield_is_wait_not_imaginary():
    d=[s for s in history() if s["series"]!="US2Y_YIELD_BP"]
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["search_bias"]=="NONE"
    assert "MISSING_US2Y_YIELD_BP" in r["reason_codes"]


def test_same_futures_contract_required():
    d=history()
    d[-3]["meeting_or_contract"]="JAN_2028"
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["search_bias"]=="NONE"
    assert "MISSING_PRE_EVENT_EXPECTED_FED_RATE_BP" in r["reason_codes"]


def test_provenance_records_reconstructed_not_realtime():
    d=history()
    for s in d:
        s["provenance_mode"]="HISTORICAL_RECONSTRUCTED"
        s["ingested_at"]="2026-11-20T00:00:00Z"
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["direction"]=="HAWKISH_REPRICING"
    assert r["source_quality"]=="HISTORICAL_ASOF_ESTIMATE_NOT_PROSPECTIVE"


def test_realtime_ingest_after_decision_is_not_known():
    d=history()
    d[-1]["ingested_at"]="2026-11-19T19:06:00Z"
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["search_bias"]=="NONE"
    assert "NO_POST_EVENT_DXY_PROXY_LEVEL" in r["reason_codes"]


def test_daily_yield_cannot_substitute_for_intraday_yield():
    d=history()
    d[-2]["bar_end_at"]="2026-11-18T20:00:00Z"
    d[-2]["published_at"]="2026-11-19T19:03:00Z"
    r=decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")
    assert r["search_bias"]=="NONE"


def test_stale_macro_quotes_are_wait():
    d=history()
    r=decide(EVENT,d,decision_at="2026-11-19T19:14:30Z")
    assert r["direction"]=="WAIT"
    assert any(c.startswith("STALE_") for c in r["reason_codes"])


def test_event_after_valid_window_never_forces_direction():
    r=decide(EVENT,history(),decision_at="2026-11-19T19:30:00Z")
    assert r["stage"]=="EXPIRED_EVENT_WINDOW"
    assert r["search_bias"]=="NONE"


@pytest.mark.parametrize("bad",[
    {"series":"EXPECTED_FED_RATE_BP","unit":"PROBABILITY_PCT"},
    {"series":"DXY_PROXY_LEVEL","is_official_ice_dxy":True},
    {"series":"EXPECTED_FED_RATE_BP","meeting_or_contract":None},
    {"series":"US2Y_YIELD_BP","published_at":"2026-11-19T19:03:00"},
    {"series":"DXY_PROXY_LEVEL","source_url":"http://example.org/data"},
])
def test_source_integrity_fails_closed(bad):
    d=history()
    target=next(s for s in d if s["series"]==bad["series"])
    target.update(bad)
    with pytest.raises(ValueError):
        decide(EVENT,d,decision_at="2026-11-19T19:05:00Z")

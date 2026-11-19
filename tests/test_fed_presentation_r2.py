"""The three Fed output fields must never contradict their own source."""
import copy
import pytest
from tests.test_fed_official_communications_r2 import (
    make,actual_hold,STATEMENT_AT,MINUTES_AT,market)
from research.fed_expectation_r1.official_communications_r2 import decide_communication
from research.fed_expectation_r1.presentation_r2 import present_r2

def test_hawkish_minutes_keep_actual_hold_and_sell_watch_not_order():
    statement=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    minutes=make()
    r=decide_communication([statement,minutes],decision_at="2026-11-19T19:00:00Z")
    p=present_r2(r)
    assert p["actual_fomc"]["title"]=="ACTUAL RATE HOLD"
    assert p["actual_fomc"]["actual_delta_bp"]==0
    assert p["communication"]["title"]=="HAWKISH COMMUNICATION"
    assert p["communication"]["minutes_meeting_date"]=="2026-10-28"
    assert p["gold_bias"]["watch"]=="SELL ON REBOUND — WATCH ONLY"
    assert p["gold_bias"]["search_bias_after_market_confirmation"]=="NONE"
    assert p["gold_bias"]["not_an_entry_order"]
    assert p["confidence_probability"] is None

def test_dovish_minutes_show_buy_watch_not_sell():
    r=decide_communication([make(tone="DOVISH")],
        decision_at="2026-11-18T19:05:00Z")
    p=present_r2(r)
    assert p["communication"]["title"]=="DOVISH COMMUNICATION"
    assert p["gold_bias"]["watch"]=="BUY THE DIP — WATCH ONLY"

def test_dissent_hawkish_does_not_mislabel_actual_hold():
    r=decide_communication([make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())],
        decision_at="2026-10-28T18:05:00Z")
    p=present_r2(r)
    assert p["actual_fomc"]["title"]=="ACTUAL RATE HOLD"
    assert p["gold_bias"]["watch"]=="WAIT"

@pytest.mark.parametrize("wrong_bias",["SEARCH_BUY_DIP","WAIT"])
def test_hawkish_watch_cannot_render_buy_or_wait_in_ui(wrong_bias):
    r=decide_communication([make()],decision_at="2026-11-18T19:05:00Z")
    r["macro_watch_bias"]=wrong_bias
    with pytest.raises(ValueError,match="INVERTED_HAWKISH_DOVISH_UI_MAPPING"):
        present_r2(r)

def test_action_vs_surprise_separate():
    a=actual_hold(
        expected_delta_bp=-25,expected_observed_at="2026-10-28T17:55:00Z",
        expected_ingested_at="2026-10-28T17:56:00Z",
        expectation_source_url="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html")
    r=decide_communication([make("FOMC_STATEMENT",released=STATEMENT_AT,actual=a)],
        decision_at="2026-10-28T18:05:00Z")
    p=present_r2(r)
    assert p["actual_fomc"]["title"]=="ACTUAL RATE HOLD"
    assert p["actual_fomc"]["rate_surprise_bp"]==25
    assert p["communication"]["title"]=="HAWKISH COMMUNICATION"
    assert p["gold_bias"]["watch"]=="SELL ON REBOUND — WATCH ONLY"

def test_no_fake_probability_or_filled_trade():
    r=decide_communication([],decision_at="2026-11-20T11:00:00Z")
    p=present_r2(r)
    assert p["gold_bias"]["watch"]=="WAIT"
    assert p["no_order_authority"] is True
    assert p["forecast_accuracy"] is None

def test_market_confirmation_conflict_must_remain_none():
    d=make()
    m=market(d["id"],"SEARCH_BUY_DIP",at="2026-11-18T19:03:00Z")
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z",market_context=m)
    p=present_r2(r)
    assert p["gold_bias"]["search_bias_after_market_confirmation"]=="NONE"
    assert "DISAGREE_WITH_TEXT" in str(p["gold_bias"]["reason_codes"])

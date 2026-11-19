"""Deterministic synthetic R2 tests: document integrity, policy priority, PIT.

These tests are NOT XAU win rates and do not confirm a headline alone
can predict a profitable sell/buy. No network; no live execution.
"""
from copy import deepcopy
from hashlib import sha256
import pytest
from research.fed_expectation_r1.official_communications_r2 import (
    decide_communication,validate_document,official_https,
)

STATEMENT_AT="2026-10-28T18:00:00Z"
MINUTES_AT="2026-11-18T19:00:00Z"
HAWK="further action to raise the target range for the federal funds rate"
DOVE="reductions in the target range for the federal funds rate may be appropriate"
DISSENT="who preferred to raise the target range for the federal funds rate by 1/4 percentage point at this meeting"

def make(kind="FOMC_MINUTES",tone="HAWKISH",released=MINUTES_AT,
         ingested=None,scope=None,actual=None,source_url=None):
    phrase=HAWK if tone=="HAWKISH" else DOVE
    if tone=="NEUTRAL":phrase="policy will continue to depend on incoming data"
    text="Federal Open Market Committee official document. "+phrase+"."
    if kind=="FOMC_STATEMENT":
        text="Federal Open Market Committee statement. "+DISSENT+"."
        phrase=DISSENT
        scope="DISSENT"
    doc={
        "id":f"TEST-{kind}","kind":kind,
        "released_at":released,"ingested_at":ingested or released,
        "source_url":source_url or "https://www.federalreserve.gov/monetarypolicy/test.htm",
        "source_text":text,
        "source_text_sha256":sha256(text.encode()).hexdigest(),
        "evidence":[{
            "excerpt":phrase,"tone":tone,"scope":scope or ("INDIVIDUAL" if kind.endswith("_SPEECH") else "COMMITTEE_OUTLOOK"),
            "topic":"MONETARY_POLICY","review_status":"HUMAN_REVIEWED",
        }]
    }
    if kind=="FOMC_MINUTES":
        doc["meeting_end_date"]="2026-10-28"
    if kind.endswith("_SPEECH"):
        doc["speaker"]="A. Example, Federal Reserve Governor"
    if actual is not None:
        decision=("maintain" if actual["target_lower_bp"]==actual["prior_lower_bp"]
                  else "raise" if actual["target_lower_bp"]>actual["prior_lower_bp"]
                  else "lower")
        anchor=f"The Committee decided to {decision} the target range for the federal funds rate"
        doc["source_text"]+=" "+anchor+"."
        doc["source_text_sha256"]=sha256(doc["source_text"].encode()).hexdigest()
        doc["actual_policy_evidence"]=anchor
        doc["actual"]=actual
    return doc

def actual_hold(**extra):
    return dict(target_lower_bp=375,target_upper_bp=400,
                prior_lower_bp=375,prior_upper_bp=400,
                dissenting_hike_votes=2,**extra)

def market(event_id,side,at=MINUTES_AT,quality="CAPTURED_REALTIME"):
    return {"event_id":event_id,"search_bias":side,
            "data_ready":True,"source_quality":quality,
            "decision_at":at}

def test_actual_oct_2026_hold_is_not_mislabelled_hike_by_dissent():
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    r=decide_communication([d],decision_at="2026-10-28T18:05:00Z")
    assert r["actual_fomc"]["decision"]=="HOLD"
    assert r["actual_fomc"]["actual_delta_bp"]==0
    assert r["actual_fomc"]["dissenting_hike_votes"]==2
    assert r["headline_stance"]=="NEUTRAL"
    assert r["macro_watch_bias"]=="WAIT"

def test_minutes_only_become_hawkish_on_nov_18_release():
    statement=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    minutes=make()
    pre=decide_communication([statement,minutes],decision_at="2026-11-17T19:30:00Z")
    assert pre["macro_watch_bias"]=="WAIT"
    now=decide_communication([statement,minutes],decision_at="2026-11-19T19:30:00Z")
    assert now["source_kind"]=="FOMC_MINUTES"
    assert now["macro_watch_bias"]=="SEARCH_SELL_REBOUND"
    assert now["trade_search_bias"]=="NONE"
    assert now["released_at"]==MINUTES_AT.replace("Z","+00:00")

def test_dovish_minutes_generate_buy_watch_but_no_orders():
    d=make(tone="DOVISH")
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z")
    assert r["headline_stance"]=="DOVISH"
    assert r["macro_watch_bias"]=="SEARCH_BUY_DIP"
    assert r["trade_search_bias"]=="NONE"
    assert r["authority_to_send_orders"] is False

def test_matching_real_market_context_does_not_grant_order_authority():
    d=make()
    m=market(d["id"],"SEARCH_SELL_REBOUND",at="2026-11-18T19:03:00Z")
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z",market_context=m)
    assert r["trade_search_bias"]=="SEARCH_SELL_REBOUND"
    assert r["stage"]=="MACRO_DIRECTION_CONFIRMED_RESEARCH_ONLY"
    assert r["authority_to_deploy"] is False
    assert r["authority_to_send_orders"] is False

def test_hawkish_text_vs_dovish_yield_dollar_conflict_is_wait():
    d=make()
    m=market(d["id"],"SEARCH_BUY_DIP",at="2026-11-18T19:03:00Z")
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z",market_context=m)
    assert r["macro_watch_bias"]=="SEARCH_SELL_REBOUND"
    assert r["stage"]=="MACRO_CONTRADICTION_WAIT"
    assert r["trade_search_bias"]=="NONE"

def test_historical_reconstruction_cannot_authorize_search():
    d=make()
    m=market(d["id"],"SEARCH_SELL_REBOUND",
             quality="HISTORICAL_ASOF_ESTIMATE_NOT_PROSPECTIVE")
    r=decide_communication([d],decision_at="2026-11-18T19:01:00Z",market_context=m)
    assert r["trade_search_bias"]=="NONE"
    assert "MARKET_CONFIRMATION_NOT_CAPTURED_REALTIME" in r["reason_codes"]

def test_market_data_for_different_fomc_cannot_bleed_through():
    d=make()
    m=market("OTHER-OLD-EVENT","SEARCH_SELL_REBOUND")
    r=decide_communication([d],decision_at="2026-11-18T19:03:00Z",market_context=m)
    assert "MARKET_CONTEXT_EVENT_ID_MISMATCH" in r["reason_codes"]

def test_later_report_captured_after_decision_is_unavailable():
    d=make(ingested="2026-11-18T19:08:00Z")
    r=decide_communication([d],decision_at="2026-11-18T19:03:00Z")
    assert r["stage"]=="NO_VERIFIED_COMMUNICATION"

def test_minutes_meeting_date_not_treated_as_release_timestamp():
    d=make()
    assert d["meeting_end_date"]=="2026-10-28"
    r=decide_communication([d],decision_at="2026-10-29T18:00:00Z")
    assert r["macro_watch_bias"]=="WAIT"

def test_actual_hold_surprise_hawkish_if_premarket_expected_cut():
    a=actual_hold(
        expected_delta_bp=-25,
        expected_observed_at="2026-10-28T17:55:00Z",
        expected_ingested_at="2026-10-28T17:56:00Z",
        expectation_source_url="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    )
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=a)
    r=decide_communication([d],decision_at="2026-10-28T18:05:00Z")
    assert r["actual_fomc"]["decision"]=="HOLD"
    assert r["actual_fomc"]["surprise_bp"]==25
    assert r["headline_stance"]=="HAWKISH"
    assert r["macro_watch_bias"]=="SEARCH_SELL_REBOUND"

def test_expected_surprise_cannot_be_backfilled_from_post_release_quote():
    a=actual_hold(
        expected_delta_bp=25,
        expected_observed_at="2026-10-28T18:01:00Z",
        expected_ingested_at="2026-10-28T18:01:00Z",
        expectation_source_url="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
    )
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=a)
    with pytest.raises(ValueError,match="LOOKAHEAD"):
        decide_communication([d],decision_at="2026-10-28T18:05:00Z")

def test_actual_hike_while_expected_unknown_is_action_not_verified_surprise():
    a=dict(target_lower_bp=400,target_upper_bp=425,
           prior_lower_bp=375,prior_upper_bp=400)
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=a)
    r=decide_communication([d],decision_at="2026-10-28T18:05:00Z")
    assert r["actual_fomc"]["actual_delta_bp"]==25
    assert r["actual_fomc"]["surprise_bp"] is None
    assert r["headline_stance"]=="HAWKISH"
    assert r["trade_search_bias"]=="NONE"

def test_latest_minutes_overrides_old_statement_not_backdated():
    stmt=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    mins=make()
    assert decide_communication([stmt,mins],decision_at="2026-11-18T20:00:00Z")["source_kind"]=="FOMC_MINUTES"

def test_fomc_statement_prioritized_over_same_day_speech():
    stmt=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    talk=make("FED_VOTING_MEMBER_SPEECH","HAWKISH",
              released="2026-10-28T19:00:00Z")
    r=decide_communication([stmt,talk],decision_at="2026-10-28T19:05:00Z")
    assert r["source_kind"]=="FOMC_STATEMENT"
    assert r["headline_stance"]=="NEUTRAL"

def test_newer_speech_can_update_outdated_previous_fomc():
    stmt=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    talk=make("FED_CHAIR_SPEECH","DOVISH",
              released="2026-11-12T15:00:00Z")
    r=decide_communication([stmt,talk],decision_at="2026-11-12T15:05:00Z")
    assert r["source_kind"]=="FED_CHAIR_SPEECH"
    assert r["macro_watch_bias"]=="SEARCH_BUY_DIP"

def test_mixed_minutes_neither_auto_sell_nor_auto_buy():
    d=make()
    extra=" "+DOVE+"."
    d["source_text"]+=extra
    d["source_text_sha256"]=sha256(d["source_text"].encode()).hexdigest()
    d["evidence"].append({
        "excerpt":DOVE,"tone":"DOVISH","scope":"COMMITTEE_OUTLOOK",
        "topic":"MONETARY_POLICY","review_status":"HUMAN_REVIEWED",
    })
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z")
    assert r["headline_stance"]=="MIXED"
    assert r["macro_watch_bias"]=="WAIT"

def test_forbidden_non_monetary_speech_claim_rejected():
    d=make("FED_CHAIR_SPEECH")
    d["evidence"][0]["topic"]="BANK_REGULATION"
    with pytest.raises(ValueError,match="NONMONETARY"):
        validate_document(d)

def test_unreviewed_sentiment_cannot_produce_recommendation():
    d=make()
    d["evidence"][0]["review_status"]="UNVERIFIED_LLM"
    with pytest.raises(ValueError,match="UNREVIEWED"):
        validate_document(d)

def test_quote_must_be_present_in_official_text():
    d=make()
    d["evidence"][0]["excerpt"]="the fed will suddenly cut 100 basis points tomorrow"
    with pytest.raises(ValueError,match="QUOTE_NOT_IN_OFFICIAL"):
        validate_document(d)

@pytest.mark.parametrize("url",[
    "http://www.federalreserve.gov/x",
    "https://federalreserve.gov.evil.example/x",
    "https://evil.example/x",
    "https://www.federalreserve.gov@evil.example/x",
])
def test_unofficial_source_is_rejected(url):
    d=make(source_url=url)
    assert not official_https(url)
    with pytest.raises(ValueError,match="OFFICIAL_FED"):
        validate_document(d)

def test_sha_tampered_document_rejected():
    d=make();d["source_text"]+=" extra claim"
    with pytest.raises(ValueError,match="SHA_MISMATCH"):
        validate_document(d)

def test_missing_exact_minutes_date_rejected():
    d=make();d["meeting_end_date"]="2026-10-28T00:00:00Z"
    with pytest.raises(ValueError,match="NOT_ISO_DATE"):
        validate_document(d)

def test_unreleased_future_speech_not_selected():
    d=make("FED_CHAIR_SPEECH",released="2026-11-22T18:00:00Z")
    r=decide_communication([d],decision_at="2026-11-20T18:00:00Z")
    assert r["macro_watch_bias"]=="WAIT"

def test_expired_speech_does_not_keep_weeklong_trade_bias():
    d=make("FED_VOTING_MEMBER_SPEECH",released="2026-11-02T18:00:00Z")
    r=decide_communication([d],decision_at="2026-11-20T18:00:00Z")
    assert r["macro_watch_bias"]=="WAIT"
    assert r["trade_search_bias"]=="NONE"

def test_market_timestamp_future_not_usable():
    d=make()
    m=market(d["id"],"SEARCH_SELL_REBOUND",at="2026-11-18T19:08:00Z")
    r=decide_communication([d],decision_at="2026-11-18T19:05:00Z",market_context=m)
    assert r["trade_search_bias"]=="NONE"
    assert "MARKET_CONFIRMATION_CLOCK_INVALID" in r["reason_codes"]

def test_speech_cannot_claim_committee_consensus():
    d=make("FED_VOTING_MEMBER_SPEECH",tone="HAWKISH")
    d["evidence"][0]["scope"]="COMMITTEE_OUTLOOK"
    with pytest.raises(ValueError,match="SPEECH_CANNOT_CLAIM_FOMC"):
        validate_document(d)

def test_latest_actual_is_retained_as_fact_when_minutes_tone_active():
    stmt=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    mins=make()
    r=decide_communication([stmt,mins],decision_at="2026-11-19T19:30:00Z")
    assert r["source_kind"]=="FOMC_MINUTES"
    assert r["actual_fomc"] is None  # newest minutes never invent a new rate decision
    assert r["last_fomc_actual_record"]["decision"]=="HOLD"
    assert r["last_fomc_actual_record"]["target_range_pct"]==[3.75,4.0]
    assert r["last_fomc_actual_record"]["historical_fact_not_current_directional_signal"]
    assert r["recent_communication_timeline"][0]["kind"]=="FOMC_MINUTES"
    assert r["recent_communication_timeline"][1]["kind"]=="FOMC_STATEMENT"

def test_no_future_actual_record_visible_before_fomc_release():
    stmt=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    r=decide_communication([stmt],decision_at="2026-10-28T17:59:00Z")
    assert r["last_fomc_actual_record"] is None
    assert not r["recent_communication_timeline"]

def test_hawkish_annotation_cannot_relabel_dovish_policy_phrase():
    d=make(tone="DOVISH")
    d["evidence"][0]["tone"]="HAWKISH"
    with pytest.raises(ValueError,match="HAWKISH_DOVISH_LABEL_INVERTED"):
        validate_document(d)

def test_dovish_annotation_cannot_relabel_hawkish_policy_phrase():
    d=make(tone="HAWKISH")
    d["evidence"][0]["tone"]="DOVISH"
    with pytest.raises(ValueError,match="HAWKISH_DOVISH_LABEL_INVERTED"):
        validate_document(d)

def test_negated_rate_hike_must_abstain_not_sell():
    d=make()
    phrase="The Committee is not likely to raise the target range for the federal funds rate"
    d["source_text"]="Official Fed minutes. "+phrase+"."
    d["source_text_sha256"]=sha256(d["source_text"].encode()).hexdigest()
    d["evidence"][0]["excerpt"]=phrase
    with pytest.raises(ValueError,match="NEGATED_MIXED_OR_AMBIGUOUS"):
        validate_document(d)

def test_hold_actual_cannot_claim_hike_in_metadata():
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    d["actual"]["target_lower_bp"]=400
    d["actual"]["target_upper_bp"]=425
    with pytest.raises(ValueError,match="ACTUAL_RATE_ACTION_CONFLICTS"):
        validate_document(d)

def test_dissent_not_counted_as_committee_hike_even_with_hawkish_words():
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    r=decide_communication([d],decision_at="2026-10-28T18:05:00Z")
    assert r["actual_fomc"]["decision"]=="HOLD"
    assert r["macro_watch_bias"]=="WAIT"

def test_actual_undocumented_source_phrase_rejected():
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=actual_hold())
    d["actual_policy_evidence"]="The Committee decided to raise the target range for the federal funds rate"
    with pytest.raises(ValueError,match="ANCHOR_MISSING"):
        validate_document(d)

def test_unexpected_dovish_text_during_hike_without_futures_is_wait():
    a=dict(target_lower_bp=400,target_upper_bp=425,
           prior_lower_bp=375,prior_upper_bp=400)
    d=make("FOMC_STATEMENT",released=STATEMENT_AT,actual=a)
    d["source_text"]+=" "+DOVE+"."
    d["source_text_sha256"]=sha256(d["source_text"].encode()).hexdigest()
    d["evidence"]=[{"excerpt":DOVE,"tone":"DOVISH","scope":"COMMITTEE",
                   "topic":"MONETARY_POLICY","review_status":"HUMAN_REVIEWED"}]
    r=decide_communication([d],decision_at="2026-10-28T18:05:00Z")
    assert r["actual_fomc"]["decision"]=="HIKE"
    assert r["headline_stance"]=="MIXED"
    assert r["macro_watch_bias"]=="WAIT"
    assert "UNVERIFIED_POLICY_SURPRISE_AND_OPPOSING_TEXT" in r["reason_codes"]

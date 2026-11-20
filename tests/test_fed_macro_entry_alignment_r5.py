"""R5 test: no XAU entry candidate contrary to current Fed macro direction.

All inputs are unit fixtures, NOT evidence of historical win rates.
"""
from copy import deepcopy
import pytest
from research.fed_expectation_r1.macro_entry_alignment_r5 import align_macro_v4

AT="2026-11-18T19:06:00Z"
EVENT={"event_id":"FOMC-R5-EXAMPLE","event_kind":"FOMC_MINUTES",
       "release_at":"2026-11-18T19:00:00Z",
       "source_url":"https://www.federalreserve.gov/monetarypolicy/fomcminutes20261028.htm"}

def macro(side="SELL"):
    return {
        "contract":"FED_R4_POLICY_INFORMATION_XAU_READONLY_V1",
        "event_id":EVENT["event_id"],
        "decision_at":"2026-11-18T19:05:00Z",
        "market_data_status":"VALIDATED_CAPTURED_PRE_POST_INTRADAY",
        "policy_information_regime":"POLICY_LIKE",
        "direction":side,
        "watch_bias":"SEARCH_SELL_REBOUND" if side=="SELL" else
                     "SEARCH_BUY_DIP" if side=="BUY" else "WAIT",
        "predicted_probability":None,
        "verified_80pct_both_sides":False,
        "authority_to_send_orders":False,
        "authority_to_deploy":False,
    }

def v4(buy="ENTRY_CANDIDATE",sell="ENTRY_CANDIDATE"):
    return [
        {"side":"BUY","setup_type":"TREND_REJECTION","stage":"RECLAIM_DETECTED",
         "entry_status":buy,"quote_ok":True,"watch_level":100,"invalidation":99},
        {"side":"SELL","setup_type":"COUNTERTREND_REVERSAL","stage":"MSS_CONFIRMED",
         "entry_status":sell,"quote_ok":True,"watch_level":100,"invalidation":101}
    ]

def test_sell_macro_blocks_buy_even_if_v4_buy_qualified():
    candidates=v4();original=deepcopy(candidates)
    r=align_macro_v4(candidates,macro("SELL"),EVENT,evaluated_at=AT)
    assert r["raw_v4_entry_candidate_n"]==2
    assert r["aligned_entry_candidate_n"]==1
    assert r["macro_direction"]=="SELL"
    assert [x["macro_alignment_gate"] for x in r["research_candidates"]]==[
        "BLOCKED_OPPOSITE_MACRO_DIRECTION","ALIGNED_RESEARCH_CANDIDATE"]
    assert candidates==original
    assert not r["authority_to_send_orders"] and not r["eligible_for_live"]

def test_buy_macro_blocks_sell_even_if_v4_sell_qualified():
    r=align_macro_v4(v4(),macro("BUY"),EVENT,evaluated_at=AT)
    assert r["aligned_entry_candidate_n"]==1
    assert [x["macro_alignment_gate"] for x in r["research_candidates"]]==[
        "ALIGNED_RESEARCH_CANDIDATE","BLOCKED_OPPOSITE_MACRO_DIRECTION"]

def test_wait_macro_blocks_all_entries():
    r=align_macro_v4(v4(),macro("WAIT"),EVENT,evaluated_at=AT)
    assert r["macro_direction"]=="WAIT"
    assert r["aligned_entry_candidate_n"]==0
    assert all("BLOCKED" in x["macro_alignment_gate"] for x in r["research_candidates"])

def test_macro_buy_does_not_create_v4_setup():
    r=align_macro_v4(v4(buy="WATCH_ONLY",sell="ENTRY_CANDIDATE"),
                     macro("BUY"),EVENT,evaluated_at=AT)
    assert r["aligned_entry_candidate_n"]==0
    assert r["research_candidates"][0]["macro_alignment_gate"]=="V4_NO_ENTRY_SETUP"

def test_macro_event_released_in_future_never_entry():
    e={**EVENT,"release_at":"2026-11-18T19:10:00Z"}
    r=align_macro_v4(v4(),macro("SELL"),e,evaluated_at=AT)
    assert r["macro_reason"]=="FOMC_NOT_YET_RELEASED"
    assert r["aligned_entry_candidate_n"]==0

def test_old_fomc_macro_cannot_direct_entries_for_days_or_weeks():
    r=align_macro_v4(v4(),macro("SELL"),EVENT,
                     evaluated_at="2026-11-19T19:06:00Z")
    assert r["macro_reason"]=="FOMC_CONTEXT_EXPIRED_REEVALUATE_FRESH_MACRO"
    assert r["aligned_entry_candidate_n"]==0

def test_captured_macro_quote_stale_over_ten_minutes():
    r=align_macro_v4(v4(),macro("SELL"),EVENT,
                     evaluated_at="2026-11-18T19:17:00Z")
    assert r["macro_reason"]=="MACRO_DIRECTION_STALE_OR_FUTURE"
    assert r["aligned_entry_candidate_n"]==0

def test_reconstructed_expost_market_data_never_allow_entry():
    x=macro("SELL");x["market_data_status"]="RETROSPECTIVE_USMPD"
    r=align_macro_v4(v4(),x,EVENT,evaluated_at=AT)
    assert r["macro_reason"]=="MACRO_MARKET_DATA_NOT_PIT_VERIFIED"
    assert r["aligned_entry_candidate_n"]==0

def test_different_fomc_document_cannot_reuse_same_direction():
    x=macro("SELL");x["event_id"]="OLDER-FOMC"
    r=align_macro_v4(v4(),x,EVENT,evaluated_at=AT)
    assert r["macro_reason"]=="MACRO_EVENT_ID_MISMATCH"
    assert r["aligned_entry_candidate_n"]==0

def test_fake_80percent_probability_claim_fails_closed():
    x=macro("BUY");x["predicted_probability"]=.80
    r=align_macro_v4(v4(),x,EVENT,evaluated_at=AT)
    assert r["macro_reason"]=="UNTRUSTED_MACRO_EXECUTION_OR_ACCURACY_CLAIM"
    assert r["aligned_entry_candidate_n"]==0

def test_error_when_side_duplicate_or_missing():
    x=v4();x[0]["side"]="SELL"
    with pytest.raises(ValueError,match="UNIQUE_SYMMETRIC"):
        align_macro_v4(x,macro(),EVENT,evaluated_at=AT)

def test_reject_unofficial_fed_event_host():
    e={**EVENT,"source_url":"https://federalreserve.gov.evil.example/document"}
    with pytest.raises(ValueError,match="UNVERIFIED_FED"):
        align_macro_v4(v4(),macro(),e,evaluated_at=AT)

def test_reject_bad_v4_invalidation_geometry():
    x=v4();x[1]["invalidation"]=99.0
    r=align_macro_v4(x,macro("SELL"),EVENT,evaluated_at=AT)
    assert r["aligned_entry_candidate_n"]==0
    assert r["research_candidates"][1]["macro_alignment_gate"]=="BLOCKED_V4_INVALIDATION_GEOMETRY"

def test_reject_v4_quote_unavailable():
    x=v4();x[0]["quote_ok"]=False
    r=align_macro_v4(x,macro("BUY"),EVENT,evaluated_at=AT)
    assert r["aligned_entry_candidate_n"]==0

def test_refuses_fake_live_execution_authority_even_macro_aligned():
    x=macro("SELL");x["authority_to_send_orders"]=True
    r=align_macro_v4(v4(),x,EVENT,evaluated_at=AT)
    assert r["aligned_entry_candidate_n"]==0
    assert r["authority_to_send_orders"] is False

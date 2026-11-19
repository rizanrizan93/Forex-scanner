"""R3 macro-FOMC historical test integrity; never bless n=1 100%."""
import json
from pathlib import Path
import pytest
from scripts.replay_fed_macro_80pct_r3 import (
    features, classify, HYPOTHESES, wilson95, score_cohort,
    run, load_archive
)

def event(id,year=2023,mp2=0.03,y2=0.04,y10=0.015,usd=0.15,
          buywin=True,sellwin=False,until="2023-09-30T20:00:00+00:00"):
    labels={}
    for side,win in (("BUY",buywin),("SELL",sellwin)):
        labels[side]={"outcomes":{
            h:{"status":"EVALUATED",
               "direction_correct":win,
               "end_at_utc":until,
               "signed_net_return_pct":1.5 if win else -1.5}
            for h in ("D1","D3","D5","D10")}}
    return {
        "event_id":id,"year":year,
        "date":f"{year}-09-20",
        "release_at_utc":f"{year}-09-20T18:00:00+00:00",
        "oracle_source_row":{
            "MP2":mp2,"UST2Y":y2,"UST10Y":y10,"DXY":usd},
        "scores":labels
    }

def test_units_are_not_all_bps():
    e=event("one")
    assert features(e)=={"MP2":3.0,"UST2Y":4.0,"UST10Y":1.5,"DXY":0.15}

@pytest.mark.parametrize("signal",["MP2_ONLY","MP2_AND_2Y",
    "MP2_AND_USD","MP2_2Y_USD","MP2_2Y_10Y_USD",
    "YIELD_2Y_10Y_USD","YIELD_2Y_USD","STRONG_MP2_2Y_USD"])
def test_symmetric_hawkish_dovish_evidence_direction(signal):
    e=event("hawk")
    assert classify(e,HYPOTHESES[signal])=="SELL"
    e=event("dove",mp2=-0.03,y2=-0.04,y10=-0.015,usd=-0.15)
    assert classify(e,HYPOTHESES[signal])=="BUY"

def test_dollar_and_yields_opposing_must_wait():
    e=event("x",mp2=.03,y2=.04,y10=.02,usd=-.15)
    assert classify(e,HYPOTHESES["MP2_2Y_USD"]).startswith("WAIT")
    assert classify(e,HYPOTHESES["MP2_AND_2Y"])=="SELL"

def test_missing_price_series_not_invented():
    e=event("bad")
    e["oracle_source_row"]["DXY"]=None
    assert classify(e,HYPOTHESES["MP2_2Y_USD"])=="WAIT_MISSING_DATA"

def test_wilson_n1_100pct_not_strong_evidence():
    assert wilson95(1,1)[0]<30
    assert wilson95(8,10)[0]<80
    assert wilson95(0,0) is None

def test_single_research_event_never_qualifies_for_80pct_both_sides():
    e=event("single",buywin=True,sellwin=True)
    a=score_cohort([e],"MP2_ONLY","SELL","D1",[2023])
    assert a["direction_accuracy_pct"]==100
    assert a["eligible_n"]==1
    assert not a["candidate_80pct_point_rate"]
    assert not a["statistically_supported_80pct"]

def test_next_fomc_during_horizon_excludes_affected_event():
    first=event("one",until="2023-10-31T22:00:00+00:00")
    second=event("two",until="2023-11-08T22:00:00+00:00")
    second["release_at_utc"]="2023-10-25T18:00:00+00:00"
    s=score_cohort([first,second],"MP2_ONLY","SELL","D10",[2023])
    assert s["selected_n"]==2
    assert s["excluded_next_fomc_overlap_n"]==1
    assert s["eligible_n"]==1

def test_separate_folds_and_declared_no_production():
    e=event("sample")
    r=run([e])
    assert r["release_gate"]["production_eligible"] is False
    assert r["release_gate"]["true_live_buy_n"]==0
    assert r["release_gate"]["true_live_sell_n"]==0
    assert r["event_count"]==1
    assert r["results"]["MP2_2Y_USD"]["all_2019_2026"]["D1"]["SELL"]["eligible_n"]==1
    assert r["results"]["MP2_2Y_USD"]["all_2019_2026"]["D1"]["BUY"]["eligible_n"]==0

def test_need_all_eight_year_archives(tmp_path):
    with pytest.raises(ValueError,match="NEED_ONE_YEAR_ARCHIVE"):
        load_archive(tmp_path)

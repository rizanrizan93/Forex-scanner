"""Source-independent tests: macro oracle does not grant trading authority."""
import hashlib, json
from datetime import date,datetime,timedelta
import pytest
from scripts import replay_fed_macro_2019_2026_r1 as annual
from scripts import aggregate_fed_macro_2019_2026_r1 as aggregate

EPOCH=datetime(1899,12,30)

def serial(y,m,d,h=14,minute=0):
    return (datetime(y,m,d,h,minute)-EPOCH).total_seconds()/86400

def fake_source_rows():
    stmt=[
        {"Date":serial(2020,3,15,0),"date_time":serial(2020,3,15,17),
         "MP2":-0.08,"UST2Y":-0.15,"DXY":-0.25},
        {"Date":serial(2020,3,3,0),"date_time":serial(2020,3,3,10),
         "MP2":-0.05,"UST2Y":-0.07,"DXY":-0.21},
    ]
    full=[{"Date":serial(2020,3,3,0),"date_time":serial(2020,3,3,10),
           "MP2":0.03,"UST2Y":0.02,"DXY":0.08}]
    pc=[{"Date":serial(2020,3,3,0),"date_time":serial(2020,3,3,10,30),
         "MP2":0.03,"UST2Y":0.02,"DXY":0.08}]
    return stmt,pc,full

def test_2020_emergency_statement_without_press_cannot_be_hallucinated(monkeypatch):
    stmt,pc,full=fake_source_rows()
    def sheets(raw,path):
        return {annual.SHEETS["STATEMENT"]:stmt,
                annual.SHEETS["PRESS_CONFERENCE"]:pc,
                annual.SHEETS["FULL_MONETARY"]:full}[path]
    monkeypatch.setattr(annual,"load_sheet",sheets)
    r=annual.event_plan(b"fake",2020)
    assert len(r)==2
    assert r[0]["window"]=="FULL_MONETARY"
    assert r[0]["oracle_policy_only"]["side"]=="SELL"
    assert r[1]["window"]=="STATEMENT"
    assert r[1]["unavailable_press_conference"] is True
    assert r[1]["oracle_policy_only"]["side"]=="BUY"
    assert r[1]["no_intraday_asof_source"]

def test_repricing_units_fed_mp2_only_is_symmetric():
    assert annual.raw_policy_sign({"MP2":0.021})["side"]=="SELL"
    assert annual.raw_policy_sign({"MP2":-0.021})["side"]=="BUY"
    assert annual.raw_policy_sign({"MP2":0.008})["side"]=="WAIT"
    assert annual.raw_policy_sign({"MP2":None})["side"]=="WAIT"

def fake_label(side):
    def v(w):
        return {"status":"EVALUATED","direction_correct":w,
                "signed_net_return_pct":1 if w else -1,
                "terminal_net_usd_oz":10 if w else -10,
                "end_at_utc":"2020-03-09T22:00:00+00:00"}
    return {"outcomes":{h:v(side=="BUY") for h in annual.HORIZON_NAMES}}

def test_counterfactual_buy_and_sell_are_separately_evaluated():
    e={"event_id":"one","date":"2020-03-03",
       "oracle_policy_only":{"side":"BUY"},
       "oracle_consensus":{"side":"WAIT"},
       "scores":{"BUY":fake_label("BUY"),"SELL":fake_label("SELL")}}
    r=annual.report_stats([e],2020)
    assert r["by_method"]["MP2_ONLY"]["D5"]["BUY"]["wins"]==1
    assert r["by_method"]["MP2_ONLY"]["D5"]["SELL"]["n_evaluable"]==0
    assert r["same_event_unconditional_price_baseline"]["D5"]["SELL"]["wins"]==0

def test_aggregate_requires_all_years_and_no_production():
    with pytest.raises(ValueError,match="MISSING_YEAR"):
        aggregate.aggregate([{"year":2023}])
    years=[{"year":y,"production_ready":False,"genuine_pit_backtest":False,
            "events":[],"statement_events_expected":0,
            "real_price_sources_loaded":0,"source_failures":[],
            "stats":{}} for y in range(2019,2027)]
    r=aggregate.aggregate(years)
    assert r["asof_eligible_buy_n"]==0
    assert r["asof_eligible_sell_n"]==0
    assert r["production_ready"] is False

def test_aggregate_explicitly_excludes_next_fomc_from_weekly_hold():
    def event(id,at,until):
        scores={}
        for side in ("BUY","SELL"):
            outcomes={h:{
                "status":"EVALUATED","direction_correct":side=="BUY",
                "end_at_utc":until,"signed_net_return_pct":1.0 if side=="BUY" else -1.0,
                "terminal_net_usd_oz":10 if side=="BUY" else -10}
                for h in annual.HORIZON_NAMES}
            scores[side]={"outcomes":outcomes}
        return {"event_id":id,"date":at[:10],"release_at_utc":at,
                "oracle_policy_only":{"side":"BUY"},
                "oracle_consensus":{"side":"BUY"},"scores":scores}
    a=event("one","2020-03-03T14:00:00+00:00","2020-03-18T22:00:00+00:00")
    b=event("two","2020-03-15T21:00:00+00:00","2020-03-26T22:00:00+00:00")
    r=aggregate.summarize([a,b],"MP2_ONLY","D10","BUY",exclude_overlapping=True)
    assert r["selected"]==2
    assert r["excluded_next_fomc_overlap_n"]==1
    assert r["evaluable_n"]==1
    assert r["pit_valid_n"]==0

def test_invalid_fomc_year_is_not_guessed():
    with pytest.raises(ValueError,match="YEAR_OUTSIDE_PROTOCOL"):
        annual.event_plan(b"raw",2027)

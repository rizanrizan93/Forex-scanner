"""V3 replay unit tests; fixture paths are synthetic, never empirical alpha."""
import pandas as pd
import pytest
from scripts import replay_rejection_v3_outcomes as v3

def fixture(n=6600):
    ix=pd.date_range("2023-09-04T00:00:00Z",periods=n,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.0,"high":100.1,"low":99.9,"close":100.0},index=ix)
    return d

def event(at):
    return {
        "id":"BUY|M5 SUPPORT|"+at.isoformat(),"side":"BUY","zone_name":"M5 SUPPORT",
        "level":100.0,"invalidation":99.5,"structure_trigger":100.5,
        "signal_at":at.isoformat(),"state":"EARLY_REJECTION",
    }

def stub_once(frame,*,now,bid=None,ask=None,quote_at=None,prior_events=None):
    old=list(prior_events or [])
    if not old:
        e=event(now)
        return {"zones":[{"side":"BUY","name":"M5 SUPPORT","entry":"EARLY ENTRY CANDIDATE"}],
                "rejection_events":[e],"h1_bias":"BUY","h4_bias":"BUY"}
    return {"zones":[],"rejection_events":old,"h1_bias":"BUY","h4_bias":"BUY"}

def test_v3_matured_buy_price_outcome_has_explicit_n(monkeypatch):
    monkeypatch.setattr(v3,"calculate",stub_once)
    d=fixture()
    # At next M1 the price reaches +$4 without reaching -$3.
    d.iloc[6101,d.columns.get_loc("high")]=104.0
    r=v3.replay_v3(d,{"source":"SYNTHETIC"},start=6100,limit=2)
    b=r["results"]["ELIGIBLE_EARLY_ENTRY"]["BUY"]
    assert b["n"]==1
    assert b["3_before_3_60m"]==100
    assert r["results"]["ELIGIBLE_EARLY_ENTRY"]["SELL"]["n"]==0
    assert len([x for x in r["events"] if x["category"]=="ELIGIBLE_EARLY_ENTRY"])==1
    assert r["execution_authority"] is False

def test_v3_identical_signal_but_adverse_first_loses(monkeypatch):
    monkeypatch.setattr(v3,"calculate",stub_once)
    d=fixture()
    d.iloc[6101,d.columns.get_loc("high")]=104.0
    d.iloc[6101,d.columns.get_loc("low")]=96.0
    r=v3.replay_v3(d,{"source":"SYNTHETIC"},start=6100,limit=2)
    assert r["results"]["ELIGIBLE_EARLY_ENTRY"]["BUY"]["3_before_3_60m"]==0

def test_v3_input_requires_enough_history():
    with pytest.raises(ValueError,match="INSUFFICIENT"):
        v3.replay_v3(fixture(6200),{},start=6100,limit=10)

def test_v3_nonexistent_source_still_has_no_invented_sell_sample(monkeypatch):
    monkeypatch.setattr(v3,"calculate",lambda *a,**kw: {
        "zones":[],"rejection_events":[],"h1_bias":"UNAVAILABLE","h4_bias":"UNAVAILABLE"})
    d=fixture()
    r=v3.replay_v3(d,{"source":"SYNTHETIC"},start=6100,limit=2)
    for side in ("BUY","SELL"):
        assert r["results"]["ELIGIBLE_EARLY_ENTRY"][side]["n"]==0
        assert r["results"]["ELIGIBLE_EARLY_ENTRY"][side]["H1_direction"] is None

def test_v3_does_not_use_future_bar_to_create_signal(monkeypatch):
    calls=[]
    def observe(frame,*,now,bid=None,ask=None,quote_at=None,prior_events=None):
        calls.append((len(frame),now,frame.index[-1]))
        return {"zones":[],"rejection_events":[],"h1_bias":"WAIT","h4_bias":"WAIT"}
    monkeypatch.setattr(v3,"calculate",observe)
    d=fixture()
    v3.replay_v3(d,{"source":"SYNTHETIC"},start=6100,limit=3)
    assert calls[0][0]==6101
    assert all(now==last+pd.Timedelta(minutes=1) for _,now,last in calls)

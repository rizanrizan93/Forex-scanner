"""V4 replay correctness tests with synthetic data; not trading performance."""
import numpy as np
import pandas as pd
import pytest
from scripts import replay_rejection_v4_outcomes as v4

def fixture(n=6500):
    ix=pd.date_range("2023-09-04",periods=n,freq="min",tz="UTC")
    p=100+np.arange(n)*0.00001
    return pd.DataFrame(dict(open=p,high=p+.2,low=p-.2,close=p),index=ix)

def mock(side="BUY",regime="COUNTERTREND_REVERSAL"):
    return {"side":side,"setup_type":regime,"stage":"MSS_CONFIRMED",
            "entry_status":"ENTRY_CANDIDATE","watch_level":100.0,
            "invalidation":99.0 if side=="BUY" else 101.0,
            "mss_closed":True,"room_atr":2.0}

def test_v4_both_sides_matured(monkeypatch):
    calls=[]
    def f(frame,*,now,**kw):
        calls.append((frame.index[-1],now))
        return {"v4_setups":[mock("BUY"),mock("SELL")],"rejection_events":[],
                "h1_bias":"SELL","h4_bias":"SELL"}
    monkeypatch.setattr(v4,"calculate",f)
    d=fixture()
    # Event on first evaluation; future contains a target touch for BUY.
    d.iloc[6101,d.columns.get_loc("high")]=104
    r=v4.replay_v4(d,{"source":"SYNTHETIC"},start=6100,limit=3)
    assert r["results"]["COUNTERTREND_REVERSAL"]["BUY"]["n"]==1
    assert r["results"]["COUNTERTREND_REVERSAL"]["SELL"]["n"]==1
    assert all(n==at+pd.Timedelta(minutes=1) for at,n in calls)
    assert r["execution_authority"] is False

def test_v4_absence_of_signals_no_invented_n(monkeypatch):
    monkeypatch.setattr(v4,"calculate",lambda *a,**kw:{
        "v4_setups":[dict(mock("BUY"),entry_status="BLOCKED")],
        "rejection_events":[],"h1_bias":"WAIT","h4_bias":"WAIT"})
    r=v4.replay_v4(fixture(),{"source":"SYNTHETIC"},start=6100,limit=1)
    assert all(r["results"][s][side]["n"]==0 for s in
               ("TREND_REJECTION","COUNTERTREND_REVERSAL") for side in ("BUY","SELL"))

def test_same_bar_invalidated_and_target_is_failure():
    ix=pd.date_range("2023-09-04",periods=100,freq="min",tz="UTC")
    d=pd.DataFrame({"open":100.0,"close":100.0,"high":100.0,"low":100.0},index=ix)
    d.iloc[1,d.columns.get_loc("high")]=105
    d.iloc[1,d.columns.get_loc("close")]=96
    o=v4._barrier_before_invalidation(d,0,"BUY",3,99,60)
    assert o["target_before_invalidation"] is False
    assert o["invalidated_earlier"] is True

def test_no_history_raises():
    with pytest.raises(ValueError,match="INSUFFICIENT"):
        v4.replay_v4(fixture(6200),{},start=6100,limit=100)

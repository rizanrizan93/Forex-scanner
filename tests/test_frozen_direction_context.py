from datetime import UTC, datetime, timedelta
import pandas as pd
from fx_scanner.frozen_direction_context import context,horizon_plan,horizon_side,build_context_packet,read_context_packet,watch_zone

def sample(now,side=1):
    i=pd.date_range(end=now,periods=40,freq="h")
    c=[3000+side*k*2 for k in range(40)]
    return pd.DataFrame({"open":[v-side for v in c],"close":c,"high":[v+2 for v in c],"low":[v-2 for v in c]},index=i)
def test_causal_bias_sides():
    now=datetime(2026,11,18,12,tzinfo=UTC)
    for side,label in [(1,"BUY"),(-1,"SELL")]:
        b=sample(now,side)
        future=b.iloc[-1:].copy();future.index+=pd.Timedelta(hours=1);future.loc[:,"close"]=1
        orig=context(b,"H1",now=now,observed_at=now,market_fresh=True)
        aug=context(pd.concat([b,future]),"H1",now=now,observed_at=now,market_fresh=True)
        assert orig==aug and orig["forecast"]==label
        assert orig["execution_authority"] is False
def test_stale_and_weekend_never_signal():
    now=datetime(2026,11,18,12,tzinfo=UTC);b=sample(now)
    for later,ok in [(now,False),(now+timedelta(days=4),True)]:
        r=context(b,"H1",now=later,observed_at=now,market_fresh=ok)
        assert r["forecast"]=="WAIT" and not r["fresh"] and r["last_bias"]=="BUY"
def test_independent_h4_sell_h1_buy_rebound():
    buy={"forecast":"BUY","fresh":True};sell={"forecast":"SELL","fresh":True}
    r={"H1":buy,"H4":sell,"D1":buy,"W1":sell}
    assert horizon_side(r,"H1")=="BUY"
    assert horizon_side(r,"H4")=="SELL"
    assert horizon_plan(r,"H4")["setup"]=="SELL ON REBOUND"
    assert horizon_plan(r,"H4")["phase"]=="POTENTIAL_REBOUND"
    assert horizon_plan(r,"D1")["phase"]=="POTENTIAL_PULLBACK"
    assert horizon_plan(r,"W1")["phase"]=="POTENTIAL_REBOUND"
def test_missing_lower_horizon_never_vetoes_valid_anchor():
    buy={"forecast":"BUY","fresh":True}
    r={"D1":buy,"H4":{"forecast":"SELL","fresh":False}}
    assert horizon_plan(r,"D1")["setup"]=="BUY THE DIP"
    assert horizon_plan(r,"D1")["phase"]=="TIMING_UNAVAILABLE_OR_NEUTRAL"
    assert horizon_plan(r,"H4")["side"]=="WAIT"
def test_same_direction_is_continuation():
    r={"H4":{"forecast":"SELL","fresh":True},"H1":{"forecast":"SELL","fresh":True}}
    assert horizon_plan(r,"H4")["phase"]=="ALIGNED_CONTINUATION"
    assert horizon_plan(r,"H1")["phase"]=="WAIT_LOCAL_CONFIRMATION"
    assert horizon_plan(r,"H4")["execution_authority"] is False
def test_native_packet_excludes_future():
    now=datetime(2026,11,18,12,tzinfo=UTC);b=sample(now)
    rows=[{"timestamp":t.isoformat(),**v.to_dict()} for t,v in b.iterrows()]
    p=build_context_packet({"H1":rows},now=now)
    frames,at=read_context_packet(p,now)
    assert len(frames["H1"])==39 and frames["H1"].index[-1]==pd.Timestamp(now)


def test_each_horizon_zone_independent_and_shared_geometry():
    now=datetime(2026,11,18,12,tzinfo=UTC)
    result={}
    for tf,side in [("H1",1),("H4",-1),("D1",1),("W1",-1)]:
        f=sample(now,side)
        r=context(f,tf,now=now,observed_at=now,market_fresh=True)
        z=watch_zone(f,r)
        assert z and z["tf"]==tf and z["side"]==("BUY" if side==1 else "SELL")
        assert z["low"]<z["high"] and z["distance"]>=0
        assert z["active"] and z["execution_authority"] is False and z["probability"] is None
        recent=f.tail(20)
        assert z["high"]-z["low"]==.25*(recent.high.max()-recent.low.min())
        result[tf]=z
    assert result["H1"]["side"]!=result["H4"]["side"]

def test_historical_zone_preserved_but_not_active_and_no_future():
    now=datetime(2026,11,18,12,tzinfo=UTC)
    f=sample(now,-1)
    r=context(f,"H4",now=now,observed_at=now,market_fresh=False)
    z=watch_zone(f,r)
    extra=f.iloc[-1:].copy();extra.index=extra.index+pd.Timedelta(hours=1)
    extra["high"]=10000.
    assert z==watch_zone(pd.concat([f,extra]),r)
    assert z["state"]=="HISTORIS" and not z["active"]
    assert watch_zone(None,r) is None
    assert watch_zone(f,{**r,"last_bias":"NETRAL"}) is None
    assert watch_zone(f.tail(19),r) is None

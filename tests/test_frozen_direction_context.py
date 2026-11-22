from datetime import UTC, datetime, timedelta
import pandas as pd
from fx_scanner.frozen_direction_context import context,dominant,build_context_packet,read_context_packet

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
def test_dominant_requires_three_fresh_and_no_weekly_conflict():
    r={"forecast":"BUY","fresh":True};d={x:r for x in ("H1","H4","D1")}
    assert dominant(d)=="BUY"
    assert dominant({**d,"W1":{"forecast":"SELL","fresh":True}}).startswith("WAIT")
    assert dominant({"H1":r,"H4":r})=="WAIT DATA"
def test_native_packet_excludes_future():
    now=datetime(2026,11,18,12,tzinfo=UTC);b=sample(now)
    rows=[{"timestamp":t.isoformat(),**v.to_dict()} for t,v in b.iterrows()]
    p=build_context_packet({"H1":rows},now=now)
    frames,at=read_context_packet(p,now)
    assert len(frames["H1"])==39 and frames["H1"].index[-1]==pd.Timestamp(now)

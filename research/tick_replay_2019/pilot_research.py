"""Research-only tick signal and fill replay. NO BROKER AUTH OR LIVE ORDERS.
Uses original frozen technical entry/target definitions, but is NOT full Settlement V1.1.1:
no historical XAU macro authorization, no staged batches, no bridge/ACK settlement,
no EUR virtual-feedback degear and no combined intratick mark-to-market DD.
"""
from __future__ import annotations
import argparse, io, json, urllib.request, collections
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

BASE="https://huggingface.co/datasets/Henrik404/dukascopy-ticks/resolve/main/data"
def fetch(symbol,ym):
    with urllib.request.urlopen(f"{BASE}/{symbol}/{symbol}_{ym}.parquet?download=true",timeout=90) as r:
        raw=r.read()
    src=pq.ParquetFile(io.BytesIO(raw))
    point=int((src.metadata.metadata or {}).get(b"point",b"0"))
    if point <=0: raise RuntimeError("MISSING_POINT")
    table=src.read(columns=["timestamp","bid","ask"])
    t=table.to_pandas()
    t=t.sort_values("timestamp",kind="stable")
    t["bid"]=t["bid"].to_numpy(dtype=np.float64)/point
    t["ask"]=t["ask"].to_numpy(dtype=np.float64)/point
    invalid=(t.ask<t.bid).sum()
    if invalid>0: raise RuntimeError(f"NEGATIVE_SPREAD {symbol}: {invalid}")
    return t,{"rows":len(t),"point":point,"first":str(t.timestamp.iloc[0]),"last":str(t.timestamp.iloc[-1]),"bytes":len(raw),"negative_spreads":int(invalid)}

def m1(t):
    q=t.set_index("timestamp")
    a=q["bid"].resample("1min").ohlc().dropna()
    a["count"]=q["bid"].resample("1min").count().reindex(a.index)
    return a

def aggregate(a,minute):
    g=a.resample(str(minute)+"min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last","count":"sum"}).dropna()
    return g

def atr(a):
    tr=pd.concat([(a.high-a.low),(a.high-a.close.shift()).abs(),(a.low-a.close.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(14,min_periods=14).mean()

def strict(a):
    e50=a.close.ewm(span=50,adjust=False).mean()
    e200=a.close.ewm(span=200,adjust=False).mean()
    return pd.Series(np.where((a.close>e200)&(e50>=e50.shift(2)),1,
                       np.where((a.close<e200)&(e50<=e50.shift(2)),-1,0)),index=a.index)

def xau_signals(one):
    five=aggregate(one,5)
    f=aggregate(one,15)
    h=aggregate(one,60)
    bias15=strict(f).reindex(five.index,method="ffill")  # shifted below to completed candle
    bias60=strict(h).reindex(five.index,method="ffill")
    # only fully closed 15m/60m bars can validate 5m signal
    bias15=strict(f).set_axis(f.index+pd.Timedelta(minutes=15)).reindex(five.index+pd.Timedelta(minutes=5),method="ffill").set_axis(five.index)
    bias60=strict(h).set_axis(h.index+pd.Timedelta(minutes=60)).reindex(five.index+pd.Timedelta(minutes=5),method="ffill").set_axis(five.index)
    a=atr(five)
    close=five.close
    mean=close.rolling(48).mean()
    # fit = mean + regression slope * (47/2), slope = centered OLS on 48 completed closes
    weighted=close.rolling(48).apply(lambda z:float(np.dot(np.arange(48),z)),raw=True)
    slope=(weighted-48*47/2*mean)/(48*(48*48-1)/12)
    fit=mean+slope*47/2
    std=close.rolling(48).std(ddof=0)
    lg=(close>fit.shift(1)-1.5*std.shift(1))&(close.shift(1)<=fit.shift(2)-1.5*std.shift(2))&(close>five.open)&(bias15==1)&(bias60==1)
    # frozen SELL sweep + reversal within 3 closed M5 bars
    lows=five.low.to_numpy()
    highs=five.high.to_numpy()
    closes=close.to_numpy()
    opens=five.open.to_numpy()
    av=a.to_numpy()
    sells=np.zeros(len(five),dtype=bool)
    anchors=np.full(len(five),np.nan)
    last=-100; trigger=0.; anchor=0.
    for i in range(25,len(five)):
        if 0<i-last<=3 and closes[i]<trigger-.05*av[i] and closes[i]<opens[i]:
            if bias15.iat[i]==-1 and bias60.iat[i]==-1:
                sells[i]=True
                anchors[i]=anchor+.1*av[i]
            last=-100
        if highs[i]>max(highs[i-24:i]) and closes[i]<max(highs[i-24:i]):
            last=i; trigger=lows[i]; anchor=highs[i]
    out=[]
    for i in np.flatnonzero(lg.to_numpy()|sells):
        at=five.index[i]+pd.Timedelta(minutes=5)
        if at.hour<12 or at.hour>=17 or at.dayofweek>4:continue
        if i<100 or not np.isfinite(av[i]):continue
        side=-1 if sells[i] else 1
        anch=anchors[i] if side==-1 else min(lows[max(0,i-2):i+1])-.1*av[i]
        out.append(dict(at=at,side=side,atr=float(av[i]),anchor=float(anch),symbol="XAUUSD"))
    return out

def eur_signals(one):
    f=aggregate(one,15)
    h=aggregate(one,60)
    e=h.close.ewm(span=50,adjust=False).mean()
    slope=e-e.shift(3)
    hb=pd.Series(np.where((h.close>e)&(slope>0),1,np.where((h.close<e)&(slope<0),-1,0)),index=h.index)
    hb=hb.set_axis(h.index+pd.Timedelta(minutes=60)).reindex(f.index+pd.Timedelta(minutes=15),method="ffill").set_axis(f.index)
    av=atr(f)
    prior_high=f.high.shift(1).rolling(8).max()
    prior_low=f.low.shift(1).rolling(8).min()
    body=(f.close-f.open)/(f.high-f.low).replace(0,np.nan)
    buy=(f.low<prior_low)&(f.close>prior_low)&(body>.2)
    sell=(f.high>prior_high)&(f.close<prior_high)&(body<-.2)
    out=[]
    for i in np.flatnonzero((buy|sell).to_numpy()&(hb.to_numpy()==0)&(f["count"].to_numpy()>=12)&np.isfinite(av.to_numpy())):
        at=f.index[i]+pd.Timedelta(minutes=15)
        if not(7<=at.hour<12):continue
        side=1 if buy.iat[i] else -1
        distance=max(.0005,min(.006,3*float(av.iat[i])))*.845
        out.append(dict(at=at,side=side,distance=distance,symbol="EURUSD"))
    return out

def one_trade(t,signal,cash=100,delay_seconds=2):
    # Snapshot first quote after decision+model delay. Stage-0 only, unlike frozen batch.
    at=signal["at"]+pd.Timedelta(seconds=delay_seconds)
    ts=t.timestamp.to_numpy(dtype="datetime64[ns]")
    idx=np.searchsorted(ts,np.datetime64(at.tz_localize(None)),side="left")
    if idx>=len(t):return None
    bid=t.bid.to_numpy();ask=t.ask.to_numpy()
    side=signal["side"];x=signal["symbol"]=="XAUUSD"
    slip=.10 if x else .00001
    entry=(ask[idx] if side==1 else bid[idx])+side*slip
    dist=max(.5,2.4*signal["atr"],side*(entry-signal["anchor"])) if x else signal["distance"]
    stop=entry-side*dist;target=entry+side*dist*(5.5 if x else 10)
    unit=1 if x else 1000
    risk=.121 if x else .2075
    commission=.06 if x else .03
    child_cost=dist*unit+slip*unit+2*commission
    # stage 0 child one minimum, shared equity intentionally not modelled in sample diagnostic
    cap_by_risk=int((cash*risk)//child_cost)
    cap_by_margin=int((cash*.5*200)//(entry*unit))
    qty=min(cap_by_risk,cap_by_margin,2000)
    if x:qty=min(qty,max(1,int(cash//102.5)))
    else:qty=int(qty*.4)
    if qty<1:
        return dict(at=str(signal["at"]),symbol=signal["symbol"],side=side,status="NO_INTEGER_CHILD_WITHIN_BUDGET",entry=entry,distance=dist,qty=0)
    limit=signal["at"]+pd.Timedelta(minutes=480 if x else 240)
    limit=min(limit,signal["at"].normalize()+pd.Timedelta(hours=19,minutes=59 if x else 60))
    end=min(len(t),np.searchsorted(ts,np.datetime64(limit.tz_localize(None)),side="right"))
    if end<=idx:return None
    exits=(bid[idx:end] if side==1 else ask[idx:end])
    hitstop=np.flatnonzero((exits<=stop) if side==1 else (exits>=stop))
    hittarget=np.flatnonzero((exits>=target) if side==1 else (exits<=target))
    sidx=hitstop[0] if len(hitstop) else np.inf
    tidx=hittarget[0] if len(hittarget) else np.inf
    j=int(min(sidx,tidx,end-idx-1))
    close=exits[j]
    # Current quote actual tick, with stop gap execution never made favorable.
    pnl=(side*(close-entry)*unit*qty)-(2*commission*qty)
    worst=(float(np.min(exits[:j+1])) if side==1 else float(np.max(exits[:j+1])))
    mae=side*(worst-entry)*unit*qty-2*commission*qty
    return dict(at=str(signal["at"]),exit_at=str(t.timestamp.iloc[idx+j]),symbol=signal["symbol"],side=side,status="STAGE0_TICK_PILOT",entry=float(entry),exit=float(close),qty=qty,pnl=float(pnl),mae=float(mae),stop=stop,target=target)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--months",nargs="+",default=["2019-01"])
    p.add_argument("--out",default="pilot.json")
    args=p.parse_args()
    result=dict(status="RESEARCH_TICK_PILOT_NOT_FROZEN_PORTFOLIO",period=args.months,
       exact_frozen_portfolio_parity=False,limitations=[
         "XAU historical macro/news unavailable: technical candidates not production authorization",
         "EUR frozen virtual feedback and multi-stage batches not implemented",
         "No shared portfolio equity, checkpoint ACK, broker tier margin or native fill settlement",
         "Per-trade indicative first batch only, not portfolio balance/DD",
       ],months={})
    for ym in args.months:
        m={}
        for symbol in ["XAUUSD","EURUSD"]:
            t,meta=fetch(symbol,ym)
            one=m1(t)
            sig=xau_signals(one) if symbol=="XAUUSD" else eur_signals(one)
            orders=[one_trade(t,s) for s in sig]
            statuses=collections.Counter((o or {}).get("status","INVALID") for o in orders)
            m[symbol]=dict(source=meta,m1_count=len(one),signals=len(sig),signal_first=[{**v,"at":str(v["at"])} for v in sig[:3]],
                            statuses=dict(statuses),orders=[o for o in orders if o][:200])
            print("TICK_REPLAY_PILOT",ym,symbol,"TICKS",meta["rows"],"M1",len(one),"SIGNALS",len(sig),"STAGES",dict(statuses),flush=True)
        result["months"][ym]=m
        with open(args.out,"w") as f:json.dump(result,f,indent=2,default=str)
    print("OUTPUT",args.out,flush=True)
if __name__=="__main__":main()

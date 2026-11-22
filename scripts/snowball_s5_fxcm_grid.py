"""RIZAN Snowball S5 — causal EURUSD bid/ask experiment on FXCM M1.
CROSS-FEED SCREENING ONLY. This is neither Frozen V1 native replay nor its P&L.
All 2012-2025 annual runs are independent and never place broker orders.
FXCM public source: https://github.com/fxcm/MarketData/blob/master/CandleData/README.md
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests

OUT=Path("artifacts/snowball_s5")
OUT.mkdir(parents=True,exist_ok=True)
FAMILIES=("BREAKOUT","RETEST_BREAK","SWEEP_RECLAIM","SWEEP_MSS",
          "EMA20_RECLAIM","INSIDE_BREAK","FVG_RETEST","EMA50_DIP",
          "SQUEEZE_EXPAND","FAILED_BREAK","DOUBLE_SWEEP","TWAP_RECLAIM")
SIDES=(1,-1)
LOOKBACKS=(12,36)
REGIMES=("ANY","H4_WITH","H4_AGAINST")
SESSIONS=("ALL","EUR_CORE_WIB","US_SESSION_WIB")
HOLDS=(60,120)
STOPS=(1.0,1.5)
TARGETS=(1.5,2.5)
EXPECTED_MODELS=len(FAMILIES)*len(SIDES)*len(LOOKBACKS)*len(REGIMES)*len(SESSIONS)*len(HOLDS)*len(STOPS)*len(TARGETS)
assert EXPECTED_MODELS==3456

def get_data(year:int):
    if year<2012 or year>2025:
        raise ValueError("FXCM crossfeed scope 2012-2025 only; no invented 2026 data.")
    sess=requests.Session()
    rows=[];sha={};missing=[]
    for week in range(1,54):
        url=f"https://candledata.fxcorporate.com/m1/EURUSD/{year}/{week}.csv.gz"
        response=None
        for attempt in range(3):
            try:
                response=sess.get(url,timeout=(12,35))
                if response.status_code in (404,403):break
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt==2:raise
                time.sleep(1.5*(attempt+1))
        if response.status_code in (404,403):
            missing.append(week);continue
        data=response.content
        assert data[:2]==b"\x1f\x8b",(year,week,"NON_GZIP")
        assert 1024<len(data)<6_000_000,(year,week,len(data))
        digest=hashlib.sha256(data).hexdigest()
        t=pd.read_csv(io.BytesIO(gzip.decompress(data)))
        required=("DateTime","BidOpen","BidHigh","BidLow","BidClose",
                  "AskOpen","AskHigh","AskLow","AskClose")
        assert all(c in t for c in required),(year,week,t.columns.tolist())
        rows.append(t[list(required)])
        sha[str(week)]=digest
    if len(rows)<42:raise RuntimeError(f"Insufficient FXCM M1 weeks {year}: {len(rows)}")
    d=pd.concat(rows,ignore_index=True)
    d["timestamp"]=pd.to_datetime(d.pop("DateTime"),format="%m/%d/%Y %H:%M:%S.%f",utc=True)
    d=d.drop_duplicates(subset=["timestamp"],keep="first").sort_values("timestamp")
    d=d.set_index("timestamp")
    d=d[(d.index.year==year)]
    d=d.rename(columns={"BidOpen":"bo","BidHigh":"bh","BidLow":"bl","BidClose":"bc",
                        "AskOpen":"ao","AskHigh":"ah","AskLow":"al","AskClose":"ac"})
    for col in d.columns:d[col]=pd.to_numeric(d[col],errors="raise")
    arr=d.to_numpy(np.float64)
    v=np.isfinite(arr).all(axis=1)&(arr>0).all(axis=1)
    v &= (arr[:,2]<=np.minimum(arr[:,0],arr[:,3]))&(arr[:,1]>=np.maximum(arr[:,0],arr[:,3]))
    v &= (arr[:,6]<=np.minimum(arr[:,4],arr[:,7]))&(arr[:,5]>=np.maximum(arr[:,4],arr[:,7]))
    v &= (arr[:,4]>=arr[:,0]-0.00003)&(arr[:,7]>=arr[:,3]-0.00003)
    invalid=int((~v).sum())
    d=d.iloc[np.flatnonzero(v)].copy()
    assert d.index.is_unique and d.index.is_monotonic_increasing
    assert len(d)>130000,(year,len(d))
    assert (d.index.asi8 % 60_000_000_000==0).all()
    data={"provider":"FXCM_public_M1_BID_ASK_NOT_FROZEN_V1","year":year,
          "week_count":len(rows),"missing_weeks":missing,
          "sha256_gzip_per_week":sha,"invalid_quote_rows":invalid,
          "bars":len(d),"first":str(d.index[0]),"last":str(d.index[-1]),
          "not_FP_Markets":True,
          "full_calendar_year":bool(len(rows)>=49 and d.index[0]<=pd.Timestamp(f"{year}-01-10",tz="UTC") and d.index[-1]>=pd.Timestamp(f"{year}-12-24",tz="UTC")),
          "expected_weeks_reference":52}
    return d,data

def features(d):
    m=d.resample("5min",label="right",closed="left").agg(
        o=("bo","first"),h=("bh","max"),l=("bl","min"),c=("bc","last"),n=("bc","count"))
    m.loc[m.n!=5,["o","h","l","c"]]=np.nan
    m["atr"]=pd.concat([m.h-m.l,(m.h-m.c.shift()).abs(),
         (m.l-m.c.shift()).abs()],axis=1).max(axis=1).ewm(
             alpha=1/14,adjust=False,min_periods=14).mean()
    m["ema20"]=m.c.ewm(span=20,adjust=False,min_periods=20).mean()
    m["ema50"]=m.c.ewm(span=50,adjust=False,min_periods=50).mean()
    m["twap"]=m.c.rolling(18,min_periods=18).mean()
    h=d.resample("240min",label="right",closed="left").agg(c=("bc","last"),n=("bc","count"))
    h.loc[h.n<200,"c"]=np.nan
    e20=h.c.ewm(span=20,adjust=False,min_periods=80).mean()
    e80=h.c.ewm(span=80,adjust=False,min_periods=80).mean()
    h["trend"]=np.where(e20>e80,1,np.where(e20<e80,-1,0))
    h.loc[h.c.isna(),"trend"]=0
    m["trend"]=h.trend.reindex(m.index,method="ffill",
       tolerance=pd.Timedelta(hours=4,minutes=5)).fillna(0)
    m["hour_wib"]=(m.index.tz_convert("Asia/Jakarta").hour).astype(int)
    return m

def family_signal(m,side:int,lookback:int,family:str):
    o,h,l,c,atr=m.o,m.h,m.l,m.c,m.atr
    hi=h.shift().rolling(lookback,min_periods=lookback).max()
    lo=l.shift().rolling(lookback,min_periods=lookback).min()
    prev_hi3=h.shift().rolling(3,min_periods=3).max()
    prev_lo3=l.shift().rolling(3,min_periods=3).min()
    candle=(c-o)*side>.15*atr
    bodygood=(c-o)*side>.30*atr
    # Signals are computed ONLY on completed M5; next M1 open is execution.
    if side==1:
        breakout=(c>hi+.08*atr)&bodygood
        sweep=(l<lo-.06*atr)&(c>lo)&candle
        mss=c>prev_hi3+.08*atr
        ema=(l<=m.ema20)&(c>m.ema20)&bodygood
        fvg=(l.shift(1)>h.shift(3))&(l<=l.shift(1))&(
            c>(l.shift(1)+h.shift(3))*.5)&candle
        dip=(l<m.ema50+.1*atr)&(c>m.ema50)&(c>h.shift(1))&candle
        failed=(h.shift(1)>hi.shift(1))&(c>hi)&(l<=hi)&bodygood
        twap=(l<=m.twap)&(c>m.twap)&(c.shift()<m.twap.shift())&bodygood
        inside=(h.shift(1)<h.shift(2))&(l.shift(1)>l.shift(2))&(c>h.shift(1))&bodygood
        prior_break=(c.shift(1)>hi.shift(1)+.08*atr.shift(1))
        retest=prior_break.rolling(3,min_periods=1).max().fillna(False).astype(bool)&(l<=hi+.25*atr)&(c>hi)&candle
        double_sweep=(sweep.shift(1).rolling(4,min_periods=1).max()>0)&(l<=lo+.3*atr)&(c>lo)&bodygood
        squeeze=(h.shift().rolling(4).max()-l.shift().rolling(4).min()<1.8*atr)&(c>hi)&bodygood
    else:
        breakout=(c<lo-.08*atr)&bodygood
        sweep=(h>hi+.06*atr)&(c<hi)&candle
        mss=c<prev_lo3-.08*atr
        ema=(h>=m.ema20)&(c<m.ema20)&bodygood
        fvg=(h.shift(1)<l.shift(3))&(h>=h.shift(1))&(
            c<(h.shift(1)+l.shift(3))*.5)&candle
        dip=(h>m.ema50-.1*atr)&(c<m.ema50)&(c<l.shift(1))&candle
        failed=(l.shift(1)<lo.shift(1))&(c<lo)&(h>=lo)&bodygood
        twap=(h>=m.twap)&(c<m.twap)&(c.shift()>m.twap.shift())&bodygood
        inside=(h.shift(1)<h.shift(2))&(l.shift(1)>l.shift(2))&(c<l.shift(1))&bodygood
        prior_break=(c.shift(1)<lo.shift(1)-.08*atr.shift(1))
        retest=prior_break.rolling(3,min_periods=1).max().fillna(False).astype(bool)&(h>=lo-.25*atr)&(c<lo)&candle
        double_sweep=(sweep.shift(1).rolling(4,min_periods=1).max()>0)&(h>=hi-.3*atr)&(c<hi)&bodygood
        squeeze=(h.shift().rolling(4).max()-l.shift().rolling(4).min()<1.8*atr)&(c<lo)&bodygood
    signals={"BREAKOUT":breakout,"RETEST_BREAK":retest,"SWEEP_RECLAIM":sweep,
        "SWEEP_MSS":(sweep.shift().rolling(3,min_periods=1).max()>0)&mss&bodygood,
        "EMA20_RECLAIM":ema,"INSIDE_BREAK":inside,"FVG_RETEST":fvg,
        "EMA50_DIP":dip,"SQUEEZE_EXPAND":squeeze,"FAILED_BREAK":failed,
        "DOUBLE_SWEEP":double_sweep,"TWAP_RECLAIM":twap}
    return (signals[family]&m.n.eq(5)&m.atr.gt(0)&m.c.notna()).fillna(False).to_numpy()

def outcomes(d,m,event_indices,side,hold,stop_mult,tp_mult):
    """Fill next M1 OPEN; broker bid/ask path, stop-first if both within minute."""
    if len(event_indices)==0:
        return (np.array([],dtype=np.int64),np.array([],dtype=np.float64),
                np.array([],dtype=bool),np.array([],dtype=np.float64))
    t=d.index.asi8//60_000_000_000
    mtime=m.index.asi8//60_000_000_000
    pos=np.searchsorted(t,mtime[event_indices])
    safe=np.clip(pos,0,len(d)-1)
    end=np.clip(pos+hold-1,0,len(d)-1)
    bad=np.r_[0,np.cumsum(np.diff(t)!=1)]
    good=(pos+hold<=len(d))&(t[safe]==mtime[event_indices])&(
         t[end]==mtime[event_indices]+hold-1)&(bad[end]==bad[safe])
    eidx=event_indices[good];pos=pos[good]
    if len(pos)==0:return outcomes(d,m,np.array([],dtype=int),side,hold,stop_mult,tp_mult)
    a=d.to_numpy(np.float64)
    result_idx=[];pnl=[];directions=[];maes=[]
    atr=m.atr.to_numpy(float)
    anchor=m.l.to_numpy(float) if side==1 else m.h.to_numpy(float)
    for batch in np.array_split(np.arange(len(pos)),max(1,int(np.ceil(len(pos)/300)))):
        ix=eidx[batch];p=pos[batch]
        b=a[p]
        slip=.00001
        entry=b[:,4]+slip if side==1 else b[:,0]-slip
        if side==1:
            stop=np.minimum(anchor[ix]-.05*atr[ix],entry-stop_mult*atr[ix])
        else:
            stop=np.maximum(anchor[ix]+.05*atr[ix],entry+stop_mult*atr[ix])
        risk=np.abs(entry-stop)
        spread=b[:,4]-b[:,0]
        # Nominal-only minlot feasibility from US$100, 1:200, 8% planned risk,
        # assuming EUR 1,000 units minimum. Not a real broker volume contract.
        feasible=(spread>=0)&(spread<.00030)&(risk>=.00005)&(risk<.004)&(
            1000*(risk+.00006+.00002)<=8)&(1000*entry/200<=50)
        if not feasible.any():continue
        ix=ix[feasible];p=p[feasible];entry=entry[feasible]
        stop=stop[feasible];risk=risk[feasible]
        path=a[p[:,None]+np.arange(hold)[None,:]]
        if side==1:
            target=entry+tp_mult*risk
            st=path[:,:,2]<=stop[:,None];hit=path[:,:,1]>=target[:,None]
            old_open=path[:,:,0];endprice=path[:,-1,3]-.00001
        else:
            target=entry-tp_mult*risk
            st=path[:,:,5]>=stop[:,None];hit=path[:,:,6]<=target[:,None]
            old_open=path[:,:,4];endprice=path[:,-1,7]+.00001
        either=st|hit
        first=either.argmax(axis=1)
        any_event=either.any(axis=1)
        rows=np.arange(len(p))
        stopped=any_event&st[rows,first]
        target_hit=any_event&~stopped
        if side==1:
            at_stop=np.minimum(old_open[rows,first]-.00001,stop-.00001)
            at_tp=target-.00001
        else:
            at_stop=np.maximum(old_open[rows,first]+.00001,stop+.00001)
            at_tp=target+.00001
        close=np.where(stopped,at_stop,np.where(target_hit,at_tp,endprice))
        signed=(close-entry)*side
        net=(signed-.00006)/risk
        # Absolute direction at end of intended hold, diagnostic even if stop triggered earlier.
        raw=(path[:,-1,3]-entry)>0 if side==1 else (path[:,-1,7]-entry)<0
        elapsed=np.where(any_event,first,hold-1)
        include=np.arange(hold)[None,:]<=elapsed[:,None]
        if side==1:
            adverse=np.where(include,path[:,:,2],np.inf).min(axis=1)
            mae=np.maximum(0,entry-adverse)/risk
        else:
            adverse=np.where(include,path[:,:,5],-np.inf).max(axis=1)
            mae=np.maximum(0,adverse-entry)/risk
        result_idx.extend(ix.tolist());pnl.extend(net.tolist())
        directions.extend(raw.tolist());maes.extend(mae.tolist())
    return (np.array(result_idx,dtype=int),np.array(pnl,dtype=float),
            np.array(directions,dtype=bool),np.array(maes,dtype=float))

def greedy(indices,hold,minutes):
    """Non-overlapping decisions after applying regime/session filters."""
    take=[];last=-10**15
    for j in indices:
        now=minutes[j]
        if now-last>=hold:
            take.append(j);last=now
    return np.array(take,dtype=int)

def summarise(values,correct,mae,opportunities):
    n=len(values)
    if not n:
        return {"n":0,"signals":int(opportunities),"wins":0,"correct":0,
                "net_R":0.,"profit_R":0.,"loss_R":0.,"mae_R":0.}
    positive=values[values>0];negative=values[values<0]
    return {"n":int(n),"signals":int(opportunities),"wins":int(len(positive)),
            "correct":int(correct.sum()),"net_R":float(values.sum()),
            "profit_R":float(positive.sum()),"loss_R":float(-negative.sum()),
            "mae_R":float(mae.sum())}

def run(year):
    d,provider=get_data(year)
    m=features(d)
    mins=m.index.asi8//60_000_000_000
    trend=m.trend.to_numpy()
    hr=m.hour_wib.to_numpy()
    sessions={"ALL":np.ones(len(m),bool),
      "EUR_CORE_WIB":(hr>=14)&(hr<19),"US_SESSION_WIB":(hr>=19)|(hr<1)}
    rows=[];family_examples={}
    for side in SIDES:
      for look in LOOKBACKS:
       for family in FAMILIES:
        sig=family_signal(m,side,look,family)
        eidx=np.flatnonzero(sig)
        family_examples[f"{family}|{side}|{look}"]=len(eidx)
        for hold in HOLDS:
         for smult in STOPS:
          for tp in TARGETS:
           e,p,correct,mae=outcomes(d,m,eidx,side,hold,smult,tp)
           if not len(e):
             byidx={}
           else:
             byidx={int(k):i for i,k in enumerate(e)}
           for gate in REGIMES:
            regime=(np.ones(len(m),bool) if gate=="ANY" else
                    trend==side if gate=="H4_WITH" else trend==-side)
            for sess,sessions_mask in sessions.items():
             chosen=np.flatnonzero(sig&regime&sessions_mask)
             feasible=np.array([j for j in chosen if j in byidx],dtype=int)
             trade_ix=greedy(feasible,hold,mins)
             ix=np.array([byidx[j] for j in trade_ix],dtype=int)
             q=summarise(p[ix],correct[ix],mae[ix],len(chosen))
             conf=f"{family}|{'BUY' if side>0 else 'SELL'}|LB{look}|{gate}|{sess}|H{hold}|SL{smult:g}|TP{tp:g}"
             rows.append({"config":conf,"family":family,"side":"BUY" if side>0 else "SELL",
               "lookback":look,"gate":gate,"session":sess,"hold":hold,
               "stop_atr":smult,"tp_R":tp,**q})
    assert len(rows)==EXPECTED_MODELS,(len(rows),EXPECTED_MODELS)
    scope={"study":"SNOWBALL_S5_FXCM_EURUSD_DIRECTION_FIRST","year":year,
      "provider":provider,"configurations":EXPECTED_MODELS,"rows":rows,
      "limits":["FXCM indicative bid/ask NOT matched to Frozen V1 or FP Markets",
       "Entry at next M1 open after closed M5; H4 only completed candles",
       "Intraminute ambiguous stop+target resolves STOP first",
       "Hypothetical minimum 1000 EUR units, equity 100 USD, model leverage 1:200 and 8 percent budget; no broker verification",
       "Extra orders are independent signal outcomes, no shared-wallet basket PnL or margin ladder",
       "Fixed .00001 slippage per side and .00006 round-trip commission-price equivalent",
       "Nonoverlap cooldown by maximum intended horizon per configuration",
       "Annual data downloaded independently, first weeks H4 EMA warmup excluded",
       "No leakage of next-year price path; no native C# parity; no live authority",
       "Full calendar-year quality is computed from actual first/last quotes and week counts, not inferred",
      "2026 FXCM weekly archive unavailable at discovery time and not included",
       "No trade/OHLC datasets are uploaded, source weekly SHA256 saved"]}
    file=OUT/f"s5_eurusd_{year}.json"
    file.write_text(json.dumps(scope,allow_nan=False))
    eligible=[r for r in rows if r["n"]>=30]
    top=sorted(eligible,key=lambda r:r["net_R"]/r["n"],reverse=True)[:8]
    print("S5_YEAR",json.dumps({"year":year,"provider":{k:v for k,v in provider.items() if "sha256" not in k},
      "configs":len(rows),"eligible_ge30":len(eligible),
      "top_DIAGNOSTIC_NOT_FROZEN":[{"config":v["config"],"n":v["n"],
        "mean_R":v["net_R"]/v["n"],"wins":v["wins"],"profit_R":v["profit_R"],
        "loss_R":v["loss_R"]} for v in top]},allow_nan=False),flush=True)

def aggregate(root):
    rows={}
    sources={}
    for y in range(2012,2026):
        a=list(Path(root).rglob(f"s5_eurusd_{y}.json"))
        if len(a)!=1:raise RuntimeError(f"Missing or duplicate source shard {y}: {a}")
        d=json.loads(a[0].read_text())
        assert d["year"]==y and d["configurations"]==EXPECTED_MODELS
        sources[y]={k:v for k,v in d["provider"].items() if k!="sha256_gzip_per_week"}
        rows[y]={q["config"]:q for q in d["rows"]}
    keys=set(rows[2012])
    assert len(keys)==EXPECTED_MODELS
    assert all(set(x)==keys for x in rows.values())
    def combined(k,years):
        a=[rows[y][k] for y in years]
        n=sum(x["n"] for x in a)
        v=sum(x["net_R"] for x in a)
        profit=sum(x["profit_R"] for x in a);loss=sum(x["loss_R"] for x in a)
        return {"n":n,"avg_R":v/n if n else None,
           "pf":profit/loss if loss else None,
           "wins":sum(x["wins"] for x in a),
           "direction":sum(x["correct"] for x in a)/n if n else None,
           "positive_years":sum(x["net_R"]>0 and x["n"]>=12 for x in a),
           "years":len(years),"mean_MAE_R":sum(x["mae_R"] for x in a)/n if n else None,
           "yearly_n":[x["n"] for x in a]}
    passed_train=[];passed_valid=[];results=[]
    for k in sorted(keys):
        train=combined(k,range(2012,2019))
        valid=combined(k,range(2019,2023))
        retro=combined(k,range(2023,2026))
        # Pre-declared gates: NO selection using 2023-25 retrospective outcomes.
        train_ok=train["n"]>=200 and train["avg_R"]>0.04 and (
            train["pf"] is not None and train["pf"]>=1.12) and train["positive_years"]>=5
        valid_ok=train_ok and valid["n"]>=100 and valid["avg_R"]>0.02 and (
            valid["pf"] is not None and valid["pf"]>=1.08) and valid["positive_years"]>=3
        if train_ok:passed_train.append(k)
        if valid_ok:passed_valid.append(k)
        if train_ok:
            results.append({"config":k,"train":train,"validation":valid,
                 "retrospective":retro,"passed_validation":bool(valid_ok),
                 "retrospective_qualified":bool(valid_ok and retro["n"]>=80 and
                    retro["avg_R"]>0 and retro["positive_years"]>=2)})
    o={"study":"SNOWBALL_S5_FXCM_EURUSD_2012_2025","version":"S5_AUDIT_1",
      "configurations_considered":EXPECTED_MODELS,
      "parameter_grid":"12 entry families × 2 sides × 2 lookbacks × 3 H4 regimes × 3 sessions × 2 horizons × 2 stop multiples × 2 TP multiples = 3456",
      "train":"2012-2018","validate":"2019-2022","retrospective":"2023-2025",
      "qualified_train":len(passed_train),"qualified_validation":len(passed_valid),
      "source_full_year_by_year":{str(y):v["full_calendar_year"] for y,v in sources.items()},
      "panel_full_calendar_years":all(v["full_calendar_year"] for v in sources.values()),
      "promotion_allowed":False,
      "qualified_retrospective":sum(x["retrospective_qualified"] for x in results),
      "train_selected_details":sorted(results,key=lambda z:(
          z["train"]["avg_R"] or -999),reverse=True)[:100],
      "research_only":True,"execution_authority":False,
      "frozen_v1_source_parity":False,"native_portfolio_replay":False,
      "target_10_billion_verified":False,
      "inference":"Screen signal unit-return with hypothetical costs; no ability to infer improvement to $100→$125 or terminal V1 balance.",
      "source_provenance_by_year":sources}
    p=OUT/"s5_eurusd_aggregate.json";p.write_text(json.dumps(o,indent=2,allow_nan=False))
    print("S5_AGGREGATE",json.dumps({k:v for k,v in o.items() if k not in ("train_selected_details","source_provenance_by_year")}),flush=True)
    print("S5_TOP_TRAIN",json.dumps(o["train_selected_details"][:8],allow_nan=False),flush=True)

def selftest():
    assert EXPECTED_MODELS==3456
    t=pd.date_range("2023-01-01",periods=240,freq="min",tz="UTC")
    x=np.arange(240)/10**7+1.1
    d=pd.DataFrame({"bo":x,"bh":x+.00006,"bl":x-.00006,"bc":x,
     "ao":x+.00010,"ah":x+.00016,"al":x+.00004,"ac":x+.00010},index=t)
    m=features(d)
    assert len(m)>0 and int(m.n.fillna(0).sum())==len(d)
    sig=family_signal(m,1,12,"BREAKOUT")
    assert len(sig)==len(m)
    assert all(not s for s in sig[:12])
    assert all(not x for x in outcomes(d,m,np.array([],dtype=int),1,60,1.,1.5)[1])
    print("S5_SELFTEST_PASS",json.dumps({"models":EXPECTED_MODELS,
        "patterns":len(FAMILIES)}),flush=True)

if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--year",type=int)
    cli.add_argument("--aggregate",action="store_true")
    cli.add_argument("--root",default="/tmp/snowball_s5")
    cli.add_argument("--selftest",action="store_true")
    args=cli.parse_args()
    if args.selftest:selftest()
    elif args.aggregate:aggregate(args.root)
    elif args.year is not None:run(args.year)
    else:cli.error("specify --year, --aggregate, or --selftest")

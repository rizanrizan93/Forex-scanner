"""Replay XAU V4 symmetric trend/countertrend entry CANDIDATES against real M1.

No LIVE connection beyond existing public read-only snapshot. Historical quotes
are synthetic: close +- $0.25. No claims about live fills or true spread.
"""
from __future__ import annotations
import argparse, hashlib, json
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
from fx_scanner.rejection_v2_research import calculate
from scripts.replay_rejection_v2_outcomes import COST, future, load_public, load_csv, wilson

def _barrier_before_invalidation(d, i, side, target, invalidation, horizon):
    """Conservative: if target & CLOSE invalidation same M1, invalidation first."""
    path=d.iloc[i+1:i+1+horizon]
    if len(path)!=horizon or path.index[0]!=d.index[i]+pd.Timedelta(minutes=1):
        return None
    if not (path.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all():
        return None
    entry=float(path.open.iloc[0]); k=1 if side=="BUY" else -1
    fa=np.flatnonzero((path.high.to_numpy()-entry if k==1 else entry-path.low.to_numpy())>=target+COST)
    aa=np.flatnonzero(path.close.to_numpy()<invalidation if k==1 else path.close.to_numpy()>invalidation)
    f=int(fa[0]) if len(fa) else horizon
    a=int(aa[0]) if len(aa) else horizon
    return {"target_before_invalidation":bool(f<a and f<horizon),
            "invalidated_earlier":bool(a<=f and a<horizon),
            "minutes_to_target":f+1 if f<horizon else None,
            "minutes_to_invalidation":a+1 if a<horizon else None}

def _summarize(rows):
    result={}
    for setup in ("TREND_REJECTION","COUNTERTREND_REVERSAL"):
        result[setup]={}
        for side in ("BUY","SELL"):
            r=[x for x in rows if x["setup"]==setup and x["side"]==side]
            n=len(r)
            if n==0:
                result[setup][side]={"n":0,"h1_direction_pct":None,"h4_direction_pct":None,
                    "3before3_h1_pct":None,"10before5_h4_pct":None,
                    "target3_before_frozen_invalidation_pct":None,
                    "wilson95_h1_direction":[None,None]}
                continue
            wins1=sum(x["x3"]["net_end"]>0 for x in r)
            result[setup][side]={
                "n":n,"h1_direction_pct":round(100*wins1/n,2),
                "h4_direction_pct":round(100*sum(x["x10"]["net_end"]>0 for x in r)/n,2),
                "3before3_h1_pct":round(100*sum(x["x3"]["state"]=="TARGET_FIRST" for x in r)/n,2),
                "10before5_h4_pct":round(100*sum(x["x10"]["state"]=="TARGET_FIRST" for x in r)/n,2),
                "target3_before_frozen_invalidation_pct":round(
                    100*sum(x["frozen_outcome"]["target_before_invalidation"] for x in r)/n,2),
                "wilson95_h1_direction":wilson(wins1,n),
                "median_mfe_h1":round(float(np.median([x["x3"]["mfe"] for x in r])),2),
                "median_mae_h1":round(float(np.median([x["x3"]["mae"] for x in r])),2)}
    return result

def replay_v4(raw,source,*,start=6100,limit=4000,cooldown=60):
    d=raw[["open","high","low","close"]].astype(float).copy()
    if not isinstance(d.index,pd.DatetimeIndex) or d.index.tz is None:
        raise ValueError("UTC_INDEX_REQUIRED")
    d.index=d.index.tz_convert("UTC")
    if d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError("BAD_ORDER")
    if not np.isfinite(d.to_numpy()).all():raise ValueError("NONFINITE")
    end=min(len(d)-241,start+limit)
    if start<6100 or end<=start:raise ValueError("INSUFFICIENT_HISTORY")
    state=[];events=[];last={};counter=Counter()
    for i in range(start,end):
        at=d.index[i]+pd.Timedelta(minutes=1)
        r=d.iloc[i]
        try:
            x=calculate(d.iloc[:i+1],now=at,bid=float(r.close)-COST/2,
                        ask=float(r.close)+COST/2,quote_at=at,prior_events=state)
        except (ValueError,TypeError,KeyError):
            counter["unavailable"]+=1;continue
        state=x["rejection_events"]
        counter["evaluated_m1"]+=1
        for v in x["v4_setups"]:
            setup=v["setup_type"];side=v["side"]
            counter[setup+"_"+side+"_"+v["stage"]]+=1
            if v["entry_status"]!="ENTRY_CANDIDATE":
                counter["blocked_"+side]+=int(v["stage"] in ("MSS_CONFIRMED","RECLAIM_DETECTED"))
                continue
            key=(setup,side)
            counter["raw_entry_"+setup+"_"+side]+=1
            if key in last and (at-last[key]).total_seconds()<cooldown*60:
                counter["deduplicated"]+=1;continue
            outcomes=[future(d,i,side,60,3,3),future(d,i,side,60,5,3),
                      future(d,i,side,240,10,5)]
            frozen=_barrier_before_invalidation(d,i,side,3,float(v["invalidation"]),60)
            if any(q is None for q in outcomes) or frozen is None:
                counter["censored"]+=1;continue
            e={"at_utc":at.isoformat(),"setup":setup,"side":side,
               "watch_level":v["watch_level"],"invalidation":v["invalidation"],
               "mss_closed":v["mss_closed"],"room_atr":v["room_atr"],
               "h1_bias":x["h1_bias"],"h4_bias":x["h4_bias"],
               "x3":outcomes[0],"x5":outcomes[1],"x10":outcomes[2],
               "frozen_outcome":frozen}
            events.append(e);last[key]=at
    return {"contract":"RIZAN_V4_TREND_COUNTERTREND_REPLAY_RESEARCH_1",
            "source":source,"source_data_sha256":hashlib.sha256(d.to_csv(float_format="%.6f").encode()).hexdigest(),
            "input_rows":len(d),"screened":(d.index[start].isoformat(),d.index[end-1].isoformat()),
            "cost_spread_usd_oz_assumed":COST,"cooldown_minutes":cooldown,
            "counters":dict(counter),"results":_summarize(events),"events":events,
            "execution_authority":False,"execution_influence":False,
            "cautions":[
                "Simulated quotes; no archive of executed or emitted LIVE signals",
                "Same-bar target and adverse treated as loss",
                "HTF context requires both H1 and H4 known; otherwise watch only",
                "Period already observed in prior research; not untouched holdout",
                "No >=60% claim unless BOTH BUY and SELL have meaningful n across years"
            ]}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True,choices=["public","csv"])
    ap.add_argument("--csv",type=Path)
    ap.add_argument("--start",type=int,default=6100)
    ap.add_argument("--limit",type=int,default=4000)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    if a.source=="public": d,source=load_public()
    else:
        if a.csv is None:ap.error("--csv needed")
        raw=a.csv.read_bytes(); d=load_csv(a.csv)
        mf=Path(str(a.csv)+".provenance.json")
        if not mf.exists():raise ValueError("MANIFEST_REQUIRED")
        source=json.loads(mf.read_text())
        if (source.get("sha256_csv")!=hashlib.sha256(raw).hexdigest() or
            source.get("failed_periods") or source.get("source")!="HISTDATA_XAUUSD_M1"):
            raise ValueError("SHA_OR_SOURCE_INVALID")
    result=replay_v4(d,source,start=a.start,limit=a.limit)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print("REJECTION_V4_REPLAY_SUMMARY",json.dumps({k:v for k,v in result.items() if k!="events"}))
if __name__=="__main__":main()

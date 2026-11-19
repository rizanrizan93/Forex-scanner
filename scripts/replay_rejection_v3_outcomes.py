"""V3 event-by-event historical replay on read-only XAU M1 OHLC.

Source / audit:
- M1 timestamps are UTC candle OPEN; signal after CLOSED M1.
- Replay walks one minute at a time with persisted immutable event states.
- Bid/ask not present historically: synthetic constant spread $0.50/oz.
- Forward paths are used ONLY to score matured events, never to decide signals.
- M1 same-bar target/adverse ambiguity resolves against the position.
- These are proxies, NOT actual scanner alerts, fills, or LIVE accuracy.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, UTC
from pathlib import Path
import argparse, hashlib, json
import pandas as pd
from fx_scanner.rejection_v2_research import calculate, completed
from scripts.replay_rejection_v2_outcomes import (
    COST, future, load_csv, load_public, wilson,
)

def _summarize(events):
    result={}
    for category in ("ALL_EARLY_WICK", "ELIGIBLE_EARLY_ENTRY", "ELIGIBLE_RETEST"):
        result[category]={}
        for side in ("BUY","SELL"):
            items=[e for e in events if e["category"]==category and e["side"]==side]
            n=len(items)
            if n==0:
                result[category][side]={
                    "n":0,"H1_direction":None,"H4_direction":None,
                    "3_before_3_60m":None,"5_before_3_60m":None,
                    "10_before_5_240m":None,"confirmed_M1_pct":None,
                    "invalidated_M1_60m_pct":None,
                    "breakout_M5_240m_pct":None,
                    "wilson95_3_before_3_pct":[None,None]}
                continue
            n3=sum(e["x3"]["state"]=="TARGET_FIRST" for e in items)
            result[category][side]={
                "n":n,
                "H1_direction":round(100*sum(e["x3"]["net_end"]>0 for e in items)/n,2),
                "H4_direction":round(100*sum(e["x10"]["net_end"]>0 for e in items)/n,2),
                "3_before_3_60m":round(100*n3/n,2),
                "5_before_3_60m":round(100*sum(e["x5"]["state"]=="TARGET_FIRST" for e in items)/n,2),
                "10_before_5_240m":round(100*sum(e["x10"]["state"]=="TARGET_FIRST" for e in items)/n,2),
                "confirmed_M1_pct":round(100*sum(e["post"]["confirmed_M1"] for e in items)/n,2),
                "invalidated_M1_60m_pct":round(100*sum(e["post"]["invalidated_60m"] for e in items)/n,2),
                "breakout_M5_240m_pct":round(100*sum(e["post"]["breakout_240m"] for e in items)/n,2),
                "wilson95_3_before_3_pct":wilson(n3,n),
            }
    return result

def _post_event(d,i,side,invalidation,trigger,m5):
    """Outcomes from complete forward bars, scored only after event maturation."""
    start=d.index[i]+pd.Timedelta(minutes=1)
    forward=d.iloc[i+1:i+241]
    sg=1 if side=="BUY" else -1
    def crossed(v):
        return v>invalidation if side=="SELL" else v<invalidation
    def confirmation(v):
        return v<trigger if side=="SELL" else v>trigger
    first60=forward.iloc[:60]
    after5=m5.loc[(m5.index > start) &
                  (m5.index <= start+pd.Timedelta(minutes=240))]
    return {
        "confirmed_M1":bool(any(confirmation(float(v)) for v in forward.close)),
        "invalidated_60m":bool(any(crossed(float(v)) for v in first60.close)),
        "invalidated_240m":bool(any(crossed(float(v)) for v in forward.close)),
        "breakout_240m":bool(any(crossed(float(v)) for v in after5.close)),
    }

def replay_v3(raw,provenance,*,start=6100,limit=5000,cooldown_minutes=60):
    d=raw[["open","high","low","close"]].copy()
    if not isinstance(d.index,pd.DatetimeIndex) or d.index.tz is None:
        raise ValueError("UTC_AWARE_M1_REQUIRED")
    d.index=d.index.tz_convert("UTC")
    if d.index.has_duplicates or not d.index.is_monotonic_increasing:
        raise ValueError("M1_TIMESTAMP_ORDER")
    d=d.astype(float)
    if d.isna().any().any():
        raise ValueError("M1_NAN")
    end=min(len(d)-241,start+limit)
    if start<6100 or end<=start:
        raise ValueError("M1_HISTORY_INSUFFICIENT")
    # Precalculate complete M5 bars for post-signal diagnostics only.
    all_m5=completed(d,5,d.index[-1]+pd.Timedelta(minutes=1))
    state=[];seen=set();events=[];counts=Counter();last_by_group={}
    price_sha=hashlib.sha256(d.to_csv(float_format="%.6f").encode()).hexdigest()
    for i in range(start,end):
        at=d.index[i]+pd.Timedelta(minutes=1)
        bar=d.iloc[i]
        if not (bar.high>bar.low):
            counts["no_range"]+=1
            continue
        # M1 price history is exactly the prefix; reconstructed quote is a
        # modeled cost proxy. Never access d[i+1:] until the label is scored.
        try:
            r=calculate(
                d.iloc[:i+1],now=at,
                bid=float(bar.close)-COST/2,
                ask=float(bar.close)+COST/2,
                quote_at=at,prior_events=state,
            )
        except (ValueError,TypeError,KeyError) as exc:
            counts["state_unavailable"]+=1
            if len(counts)<20: counts["exception_"+type(exc).__name__]+=1
            # Without a valid observation, state history is NOT silently
            # carried as if checked; following update will mark DATA_GAP.
            continue
        counts["evaluated_closes"]+=1
        state=r["rejection_events"]
        fresh=[e for e in state if e["id"] not in seen]
        for e in fresh:
            seen.add(e["id"])
            side=e["side"]
            matched=[z for z in r["zones"] if
                     z["side"]==side and z["name"]==e["zone_name"]]
            eligible=any(z["entry"]=="EARLY ENTRY CANDIDATE" for z in matched)
            counts["raw_early_"+side]+=1
            if eligible:counts["eligible_early_"+side]+=1
            for category in ("ALL_EARLY_WICK",
                             "ELIGIBLE_EARLY_ENTRY" if eligible else None):
                if category is None:continue
                if category in ("ELIGIBLE_EARLY_ENTRY","ELIGIBLE_RETEST"):
                    key=(category,side)
                    if key in last_by_group and (at-last_by_group[key]).total_seconds()<cooldown_minutes*60:
                        counts["cooldown_"+category+"_"+side]+=1
                        continue
                labels=(future(d,i,side,60,3,3),future(d,i,side,60,5,3),
                        future(d,i,side,240,10,5))
                if any(x is None for x in labels):
                    counts["censored_future"]+=1;continue
                events.append({
                    "id":e["id"],"at_utc":at.isoformat(),
                    "category":category,"side":side,
                    "h1_bias":r["h1_bias"],"h4_bias":r["h4_bias"],
                    "zone":e["zone_name"],"zone_level":e["level"],
                    "frozen_invalidation":e["invalidation"],
                    "x3":labels[0],"x5":labels[1],"x10":labels[2],
                    "post":_post_event(d,i,side,e["invalidation"],
                                       e["structure_trigger"],all_m5),
                })
                if category=="ELIGIBLE_EARLY_ENTRY":
                    last_by_group[(category,side)]=at
        # Optional retest entry is distinct from initial wick; freeze its own
        # timestamp and require previously observed same-side event.
        for side in ("BUY","SELL"):
            candidates=[z for z in r["zones"] if z["side"]==side and
                        z["entry"]=="RETEST RECLAIM CANDIDATE"]
            if not candidates:continue
            historical=[e for e in state if
                        e["side"]==side and e["zone_name"]==candidates[0]["name"] and
                        e["signal_at"]<at.isoformat() and
                        e["state"] in ("EARLY_REJECTION","REJECTION_CONFIRMED")]
            if not historical:continue
            key=("ELIGIBLE_RETEST",side)
            if key in last_by_group and (at-last_by_group[key]).total_seconds()<cooldown_minutes*60:
                continue
            e=historical[-1]
            labels=(future(d,i,side,60,3,3),future(d,i,side,60,5,3),
                    future(d,i,side,240,10,5))
            if any(x is None for x in labels):
                counts["censored_future"]+=1;continue
            counts["eligible_retest_"+side]+=1
            events.append({
                "id":e["id"]+"|retest|"+at.isoformat(),
                "at_utc":at.isoformat(),"category":"ELIGIBLE_RETEST",
                "side":side,"h1_bias":r["h1_bias"],"h4_bias":r["h4_bias"],
                "zone":e["zone_name"],"zone_level":e["level"],
                "frozen_invalidation":e["invalidation"],
                "x3":labels[0],"x5":labels[1],"x10":labels[2],
                "post":_post_event(d,i,side,e["invalidation"],
                                   e["structure_trigger"],all_m5),
            })
            last_by_group[key]=at
    return {
        "contract":"RIZAN_REJECTION_V3_REPLAY_RESEARCH_1",
        "source":provenance,"normalized_m1_sha256":price_sha,
        "time_contract":"M1 OPEN UTC; signal after closed M1; next M1 open hypothetical fill",
        "input_rows":len(d),
        "screened_span":[d.index[start].isoformat(),d.index[end-1].isoformat()],
        "spread_assumption_usd_oz":COST,
        "cooldown_minutes":cooldown_minutes,
        "replay_closes":counts["evaluated_closes"],
        "counters":dict(counts),"results":_summarize(events),
        "events":events,
        "limitations":[
            "Historical reconstructed candidate events; NOT archived live scanner emissions",
            "Price-only OHLC with fixed synthetic bid/ask, not broker quotes/fills",
            "Outcome path scored after signal; same-M1 ambiguous barrier is adverse first",
            "V3 regime and parameters were shaped after observing 2026; sample is not pristine holdout",
            "Cannot infer >=60% BUY AND SELL if counts too low",
            "H4 filtering may be unavailable when complete H4 history is insufficient",
        ],
        "execution_authority":False,"execution_influence":False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",choices=["public","csv"],required=True)
    p.add_argument("--csv",type=Path)
    p.add_argument("--start",type=int,default=6100)
    p.add_argument("--limit",type=int,default=5000)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    if a.source=="public": d,prov=load_public()
    else:
        if a.csv is None:p.error("--csv is required")
        d=load_csv(a.csv)
        prov={"source":"HISTORICAL_CSV"}
        manifest=Path(str(a.csv)+".provenance.json")
        if not manifest.exists():raise ValueError("SOURCE_MANIFEST_REQUIRED")
        prov=json.loads(manifest.read_text())
        if (prov.get("sha256_csv") != hashlib.sha256(a.csv.read_bytes()).hexdigest()
                or prov.get("failed_periods") or prov.get("source")!="HISTDATA_XAUUSD_M1"):
            raise ValueError("SOURCE_PROVENANCE_INVALID")
    result=replay_v3(d,prov,start=a.start,limit=a.limit)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    summary={k:v for k,v in result.items() if k!="events"}
    print("REJECTION_V3_REPLAY_SUMMARY",json.dumps(summary,allow_nan=False))
if __name__=="__main__":main()

"""R31 — high-coverage, precision-gated, independent TF zone-direction research.

Exact frozen R25/R11/R29.2/R18/R27/R24 models are NOT reconstructed here.
256 direction variants x 4096 source-TF zone rules x 8 exit variants per
timeframe. Every variant emits only historical read-only research evidence.

Causal order: source bar i closes -> zone is formed; first retest j>i closes
with directionally aligned rejection -> direction vote is computed at j using
ONLY fully closed same-TF indicators -> entry at the following bar's OPEN.
After entry, stop-first tie resolves OHLC intrabar ambiguity pessimistically.
Volume-oriented selection ONLY uses 2012-20 development and 2021-23
validation, never 2024-26 retrospective test when choosing configurations.
"""
from __future__ import annotations
import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
import research_tf_zone_direction_mega as r30

OUT=Path("artifacts/r31")
TF=("H1","H4","D1","W1")
DIRECTION_MODELS=256
ZONE_CONFIGS=4096
R_MULTS=(0.60,0.80,1.00,1.30)
HOLD_BARS=(3,8)
EXIT_VARIANTS=len(R_MULTS)*len(HOLD_BARS)
BASE_COST=.70
STRESS_EXTRA=.80
DEVMIN={"H1":100,"H4":55,"D1":22,"W1":7}
VALMIN={"H1":65,"H4":30,"D1":12,"W1":5}
EVALMIN={"H1":60,"H4":25,"D1":12,"W1":6}

def _wilson(k,n):
    return r30.wilson(int(k),int(n))

def _finite(v):
    return math.isfinite(float(v))

def events_from_closed_ohlc(d,features,tf):
    """Build sufficiently broad *candidate* retest events; no entry on touch.

    A zone requires a completed bullish/bearish displacement candle, close
    beyond preceding base, structural prior swing context, and later closed
    same-timeframe rejection. Candidate quality is screened independently.
    """
    data=d[["o","h","l","c"]].to_numpy(float)
    o,h,l,c=data.T
    atr=features["atr"]
    vol=features["vol"]
    prev_h=pd.Series(h).shift(1).rolling(5,min_periods=5).max().to_numpy()
    prev_l=pd.Series(l).shift(1).rolling(5,min_periods=5).min().to_numpy()
    n=len(d);found=[]
    # Missing bars are not interpolated. Following trading-period timestamps
    # may jump over weekends; the source-TF next open is known only later.
    for base in (1,2,3):
        for i in range(80,n-30):
            a=float(atr[i])
            if not _finite(a) or a<=0:continue
            span=h[i]-l[i]
            if span<.20*a:continue
            body=abs(c[i]-o[i])/max(span,1e-8)
            if body<.10:continue
            side=1 if c[i]>o[i] else -1
            low=float(np.min(l[i-base:i]))
            high=float(np.max(h[i-base:i]))
            width=(high-low)/a
            if not .04<=width<=3.20:continue
            if side==1:
                if c[i]<=high:continue
                bos=(c[i]-prev_h[i])/a
            else:
                if c[i]>=low:continue
                bos=(prev_l[i]-c[i])/a
            if not _finite(bos) or bos<-.25:continue
            retest=None
            for j in range(i+1,min(i+25,n-22)):
                # Distal breach before retest voids the zone.
                if side==1 and c[j]<low-.25*a:break
                if side==-1 and c[j]>high+.25*a:break
                if h[j]>=low and l[j]<=high:
                    retest=j;break
            if retest is None:continue
            j=retest
            # Close rejection candle and its side are known at END of j.
            if side==1 and not(c[j]>=low and c[j]>=o[j]):continue
            if side==-1 and not(c[j]<=high and c[j]<=o[j]):continue
            entry_i=j+1
            if entry_i>=n:continue
            # Conservative stop outside structural zone by 0.10 ATR.
            entry=float(o[entry_i])
            stop=float(low-.10*a if side==1 else high+.10*a)
            risk=(entry-stop)*side
            if not .05*a<=risk<=3.2*a:continue
            session=int(d.index[j].hour)
            strength=side*(float(c[j])-(low+high)/2)/a
            found.append({
                "formation":i,"signal_index":j,"entry_index":entry_i,
                "year":int(d.index[entry_i].year),
                "side":side,"base":base,
                "displacement":span/a,"body":body,"bos":float(bos),
                "width":width,"vol":float(vol[j]),
                "retest_lag":j-i,"rejection":float(strength),
                "hour":session,"entry":entry,"stop":stop,
                "risk":float(risk)
            })
    if not found:raise RuntimeError(f"R31_NO_ZONE_RETEST_EVENTS:{tf}")
    return found

def direction_votes(d,f,events):
    """256 variants, computed at completed rejection candle (not earlier)."""
    idx=np.asarray([e["signal_index"] for e in events],dtype=int)
    side=np.asarray([e["side"] for e in events],dtype=np.int8)
    close=d.c.to_numpy(float)
    out=[]
    for lag in (2,3,5,8,13,21,34,55):
        mom=f["mom"][lag][idx]*side>0
        for ema in (5,8,13,21):
            trend=(close[idx]-f["ema"][ema][idx])*side>0
            for cut in (47,50,53,56):
                rsi=(f["rsi"][idx]-50)*side>(cut-50)
                count=mom.astype(np.int8)+trend.astype(np.int8)+rsi.astype(np.int8)
                for votes_required in (1,2):
                    out.append(count>=votes_required)
    if len(out)!=DIRECTION_MODELS:
        raise RuntimeError("R31_DIRECTION_MODEL_COUNT_CHANGED")
    return out

def zone_axes(events):
    arr=lambda name:np.asarray([e[name] for e in events],float)
    base=arr("base");disp=arr("displacement");width=arr("width")
    bos=arr("bos");lag=arr("retest_lag");reject=arr("rejection")
    return [
        [np.ones(len(events),bool),base==1,base<=2,base>=2],
        [disp>=x for x in (.20,.35,.55,.85)],
        [width<=x for x in (3.20,2.30,1.50,.90)],
        [bos>=x for x in (-.25,-.05,.10,.25)],
        [lag<=x for x in (24,12,6,3)],
        [reject>=x for x in (-.50,-.20,0.,.15)]
    ]

def outcome_matrix(d,events):
    """Eight 0.60R..1.30R / hold-3-or-8 exit policies, net USD/oz.

    Every event is entered on next TF candle OPEN, stop-first when both
    stop and target crossed in same OHLC bar; no borrow/leverage assumption.
    """
    a=d[["o","h","l","c"]].to_numpy(float)
    o,h,l,c=a.T
    n=len(events)
    pnl=np.zeros((EXIT_VARIANTS,n),dtype=np.float64)
    exit_idx=np.zeros((EXIT_VARIANTS,n),dtype=np.int32)
    for ei,e in enumerate(events):
        j=e["entry_index"];side=e["side"];stop=e["stop"]
        entry=e["entry"];risk=e["risk"]
        for ix,(rr,hold) in enumerate((rr,hold) for hold in HOLD_BARS for rr in R_MULTS):
            tp=entry+side*rr*risk
            end=min(len(c)-1,j+hold-1)
            p=float(c[end]);ex=end
            for k in range(j,end+1):
                stop_hit=l[k]<=stop if side==1 else h[k]>=stop
                take_hit=h[k]>=tp if side==1 else l[k]<=tp
                if stop_hit:
                    p=stop;ex=k;break
                if take_hit:
                    p=tp;ex=k;break
            pnl[ix,ei]=(p-entry)*side-BASE_COST
            exit_idx[ix,ei]=ex
    return pnl,exit_idx

def report_metrics(events,mask,tf,d,pnl,exit_indices,variant,start,end,*,stress=0.):
    begin=pd.Timestamp(f"{start}-01-01",tz="UTC")
    finish=pd.Timestamp(f"{end+1}-01-01",tz="UTC")
    if len(mask)!=len(events):raise ValueError("R31_MASK_LENGTH_MISMATCH")
    ix=np.flatnonzero(mask)
    ix=[int(i) for i in ix
        if (begin<=d.index[events[i]["entry_index"]]<finish
            and d.index[exit_indices[variant,i]]<finish)]
    # Non-overlap rule is applied identically to validation and evaluation.
    ix=sorted(ix,key=lambda k:(events[k]["entry_index"],events[k]["signal_index"],k))
    kept=[];last_end=-1
    for k in ix:
        if events[k]["entry_index"]<=last_end:continue
        kept.append(k);last_end=int(exit_indices[variant,k])
    vals=np.asarray([pnl[variant,k]-stress for k in kept],float)
    wins=int((vals>0).sum());cnt=len(vals)
    gains=float(vals[vals>0].sum()) if cnt else 0.
    losses=-float(vals[vals<0].sum()) if cnt else 0.
    cumulative=np.r_[0,np.cumsum(vals)]
    dd=float((np.maximum.accumulate(cumulative)-cumulative).max())
    annual={}
    for yr in range(start,end+1):
        ym=[k for k in kept if d.index[events[k]["entry_index"]].year==yr]
        a=np.asarray([pnl[variant,k]-stress for k in ym],float)
        annual[str(yr)]={"n":len(ym),"net_usd_oz":round(float(a.sum()),5),
                         "win_rate":round(float((a>0).mean()),5) if len(a) else None}
    return {
        "n":cnt,"wins":wins,"win_rate":round(wins/cnt,6) if cnt else None,
        "wilson_lower95":round(_wilson(wins,cnt),6) if cnt else None,
        "net_usd_oz":round(float(vals.sum()),5),
        "expectancy_usd_oz":round(float(vals.mean()),5) if cnt else None,
        "profit_factor":round(gains/losses,5) if losses else None,
        "max_additive_drawdown_usd_oz":round(dd,5),
        "annual":annual
    }

def _passes(m,tf,floor):
    if m["n"]<VALMIN[tf] or m["win_rate"] is None:
        return False
    if (m["win_rate"]<floor or m["wilson_lower95"]<.485
            or m["net_usd_oz"]<=0 or m["expectancy_usd_oz"]<=0
            or m["profit_factor"] is None or m["profit_factor"]<1.12):
        return False
    annual=m["annual"]
    active=sum(annual[str(yr)]["n"]>=max(2,VALMIN[tf]//12)
               for yr in range(2021,2024))
    positive=sum(annual[str(yr)]["net_usd_oz"]>0 for yr in range(2021,2024))
    # Source W1 too sparse for a credible high-frequency annual guarantee:
    # never silently promote it without at least two profitable years.
    return active>=2 and positive>=2

def _insert(heap,key,payload,limit):
    item=(key,*payload)
    if len(heap)<limit:heapq.heappush(heap,item)
    elif key>heap[0][0]:heapq.heapreplace(heap,item)

def test_candidate(tf,modelid,cfg,variant,axes,votes,events,d,pnl,exits):
    mask=votes[modelid].copy()
    for k in range(6):
        mask &= axes[k][(cfg>>(2*k))&3]
    # Final selection uses actual unique trades net of cost and after purging.
    m=report_metrics(events,mask,tf,d,pnl,exits,variant,2021,2023)
    return mask,m

def sweep(tf,model_start=0,models=32,caps=ZONE_CONFIGS):
    if tf not in TF or not 0<=model_start<DIRECTION_MODELS:
        raise ValueError("R31_TF_OR_MODEL_RANGE_INVALID")
    if not 1<=models<=DIRECTION_MODELS-model_start or not 1<=caps<=ZONE_CONFIGS:
        raise ValueError("R31_SEARCH_LIMIT_INVALID")
    d,source=r30.load(tf)
    f=r30.prepare(d)
    events=events_from_closed_ohlc(d,f,tf)
    votes=direction_votes(d,f,events)
    axes=zone_axes(events)
    pnl,exits=outcome_matrix(d,events)
    year=np.asarray([d.index[e["entry_index"]].year for e in events],int)
    exit_year=np.asarray([[d.index[exits[v,i]].year for i in range(len(events))]
                          for v in range(EXIT_VARIANTS)],int)
    div={y:np.asarray((year>=p)&(year<=q),bool) for y,p,q
         in (("dev",2012,2020),("val",2021,2023),("eval",2024,2026))}
    axis_pack=np.asarray([[r30.pack(y) for y in ax] for ax in axes],dtype=np.uint8)
    # Split-screen masks must not count outcomes maturing after fold end.
    pools={(exitv,typ):[] for exitv in range(EXIT_VARIANTS)
           for typ in ("coverage","precision")}
    evaluated=eligible=0
    per_variant=0
    for modelid in range(model_start,model_start+models):
        pred=r30.pack(votes[modelid])
        for start in range(0,caps,256):
            ids=np.arange(start,min(start+256,caps),dtype=np.uint32)
            q=np.broadcast_to(pred,(len(ids),len(pred))).copy()
            for axis_idx in range(6):
                np.bitwise_and(q,axis_pack[axis_idx,(ids>>(2*axis_idx))&3],out=q)
            for exitv in range(EXIT_VARIANTS):
                dev=div["dev"]&(exit_year[exitv]<=2020)
                win=dev&(pnl[exitv]>0)
                packed_dev=r30.pack(dev);packed_win=r30.pack(win)
                n=np.bitwise_count(np.bitwise_and(q,packed_dev)).sum(axis=1)
                k=np.bitwise_count(np.bitwise_and(q,packed_win)).sum(axis=1)
                evaluated+=len(ids)
                per_variant+=len(ids)
                good=np.flatnonzero(n>=DEVMIN[tf])
                if not len(good):continue
                rate=k[good]/n[good]
                # Development win-rate and count jointly limit search.
                valid=good[(rate>=.52)&
                           (rate-1.96*np.sqrt(rate*(1-rate)/n[good])>=.44)]
                eligible+=len(valid)
                if not len(valid):continue
                # Always preserve high-count *and* high-precision seeds.
                order_count=valid[np.argsort(n[valid])[-min(6,len(valid)):]]
                order_precision=valid[np.argsort(
                    k[valid]/n[valid]-1.96*np.sqrt(
                        (k[valid]/n[valid])*(1-k[valid]/n[valid])/n[valid]
                    ))[-min(6,len(valid)):]]
                for kind,picks in (("coverage",order_count),
                                   ("precision",order_precision)):
                    heap=pools[(exitv,kind)]
                    for j in picks:
                        nj,kj=int(n[j]),int(k[j])
                        lb=_wilson(kj,nj)
                        key=(nj,lb) if kind=="coverage" else (lb,nj)
                        _insert(heap,key,(modelid,int(ids[j]),exitv),96)
        if modelid%8==7:
            print(json.dumps({"stage":"R31_SCREEN","tf":tf,"through_model":modelid,
                              "evaluations":evaluated,"eligible_development":eligible}),flush=True)

    # Validate only development preselected configurations. Never inspect
    # retrospective evaluation to choose the final candidate.
    selected={}
    inspected=0
    for floor,label in ((.55,"volume_55"),(.60,"precision_60")):
        ready=[];near=[]
        candidates=set()
        for (_,kind),heap in pools.items():
            for row in heap:
                candidates.add((row[1],row[2],row[3]))
        for modelid,cfg,exitv in sorted(candidates):
            mask,m=test_candidate(tf,modelid,cfg,exitv,axes,votes,events,d,pnl,exits)
            inspected+=1
            if m["n"]<VALMIN[tf]:continue
            base=(modelid,cfg,exitv,m,mask)
            if _passes(m,tf,floor):
                ready.append(base)
            else:
                near.append(base)
        ready.sort(key=lambda x:(x[3]["n"],x[3]["wilson_lower95"],
                                 x[3]["expectancy_usd_oz"]),reverse=True)
        near.sort(key=lambda x:(x[3]["n"],x[3]["win_rate"] or -1,
                                x[3]["net_usd_oz"]),reverse=True)
        def payload(row):
            modelid,cfg,exitv,val,mask=row
            rr=R_MULTS[exitv%len(R_MULTS)]
            hold=HOLD_BARS[exitv//len(R_MULTS)]
            return {
                "model_id":modelid,"config_id":cfg,
                "zone_axes":[int((cfg>>(2*i))&3) for i in range(6)],
                "reward_risk_target":rr,"holding_bars":hold,
                "validation":val,
                "retrospective_2024_2026":report_metrics(
                    events,mask,tf,d,pnl,exits,exitv,2024,2026),
                "retrospective_stress_plus_0_80_usd_oz":report_metrics(
                    events,mask,tf,d,pnl,exits,exitv,2024,2026,stress=STRESS_EXTRA),
                "candidate_hash":hashlib.sha256(r30.pack(mask)).hexdigest()
            }
        selected[label]={
            "validation_floor":floor,
            "minimum_val_trades":VALMIN[tf],
            "qualifying_candidates":len(ready),
            "pass":bool(ready),
            "most_trades_candidates":[payload(row) for row in ready[:4]],
            "near_misses_diagnostic_only":[payload(row) for row in near[:2]]
        }
    OUT.mkdir(parents=True,exist_ok=True)
    result={
        "contract":"RIZAN_R31_HIGH_COVERAGE_PRECISION_PER_TF_REPLAY_V1",
        "tf":tf,"source":r30.SOURCE[tf],"source_shard_sha256":source,
        "data_first":d.index[0].isoformat(),"data_last":d.index[-1].isoformat(),
        "historical_candles":len(d),
        "source_tf_retest_events":len(events),
        "model_start":model_start,"direction_model_variants":models,
        "zone_rule_variants":caps,"exit_policy_variants":EXIT_VARIANTS,
        "expected_evaluations":models*caps*EXIT_VARIANTS,
        "actual_evaluations":evaluated,"eligible_development_tests":eligible,
        "unique_validation_candidates_evaluated":inspected//2,
        "method":"CLOSED_SOURCE_ZONE -> FIRST_RETEST_REJECTION -> CLOSED_SAME_TF_DIRECTION -> NEXT_OPEN_ENTRY",
        "selection":"MOST_VALIDATION_TRADES_SUBJECT_TO_WIN_RATE_55_OR_60_PF_1_12_POSITIVE_EXPECTANCY_2_PROFITABLE_YEARS",
        "development":"2012-2020","validation":"2021-2023",
        "retrospective_evaluation":"2024-2026_PREVIOUSLY_STUDIED_NOT_PRISTINE",
        "cost_scenario_usd_oz":BASE_COST,"stress_extra_cost_usd_oz":STRESS_EXTRA,
        "tiers":selected,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"frozen_model_parity":False,
        "limitations":[
            "Challenger features are not exact frozen R25/R11/R29.2/R18/R27/R24 forecasts",
            "OHLC bar-replay cannot establish real intrabar M15/M5 confirmations; conservative stop-first ties",
            "Retrospective 2024-26 is not pristine; 8.39M search across four TF has strong multiple-testing risk",
            "No verified FP Markets spread/slippage/commission/financing; net USD/oz is cost scenario only",
            "Same-timeframe models are independently selected but NOT proven live profitable",
            "Signal count after no-overlap (one active trade per TF) is lower than raw candidate count",
            "No recommendation or automatic promotion to Frozen V1 or manual ForexScanner production"
        ]
    }
    out=OUT/f"r31-{tf}-models-{model_start}.json"
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R31_DONE","tf":tf,"models":models,
                      "actual_evaluations":evaluated,"events":len(events),
                      "tiers":{key:{"qualifying":value["qualifying_candidates"],
                                    "best_val_n":value["most_trades_candidates"][0]["validation"]["n"]
                                    if value["most_trades_candidates"] else None,
                                    "best_eval_n":value["most_trades_candidates"][0]["retrospective_2024_2026"]["n"]
                                    if value["most_trades_candidates"] else None}
                               for key,value in selected.items()}}),flush=True)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=TF,required=True)
    p.add_argument("--model-start",type=int,default=0)
    p.add_argument("--models",type=int,default=32)
    p.add_argument("--zone-configs",type=int,default=ZONE_CONFIGS)
    a=p.parse_args()
    sweep(a.tf,a.model_start,a.models,a.zone_configs)

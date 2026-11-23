"""R31B dense validation audit of the SAME R31 hypothesis family.

Instead of selecting only top development win-rate/volume heaps, pre-screen
all direction x zone x exit combinations on development and validation packed
event masks. Exact final selection still uses no-overlap, realized-cost
scenario, >=2 profitable validation years, and 2024-26 is never used to rank.
This is NOT a new independent historical holdout, and counts are re-evaluated
combinations in the SAME parameter universe, NOT new strategy families.
"""
from __future__ import annotations
import argparse, hashlib, heapq, json
from pathlib import Path
import numpy as np
import pandas as pd
import research_r31_high_coverage_precision as r31

TF=r31.TF
OUT=Path("artifacts/r31b")
CONFIGS=r31.ZONE_CONFIGS
EXIT=r31.EXIT_VARIANTS
MODELS=r31.DIRECTION_MODELS

def top_indices(valid,n,win,limit=5,kind="volume"):
    if not len(valid):return np.asarray([],dtype=int)
    rate=win[valid]/np.maximum(n[valid],1)
    if kind=="volume":
        score=n[valid]+1e-4*rate
    else:
        score=rate-1.96*np.sqrt(np.clip(rate*(1-rate),0,1)/np.maximum(n[valid],1))
    return valid[np.argsort(score)[-min(limit,len(valid)):]]

def shortlist_add(pool,key,ident,limit):
    item=(key,*ident)
    if len(pool)<limit:
        heapq.heappush(pool,item)
    elif item[0]>pool[0][0]:
        heapq.heapreplace(pool,item)

def annotated(row,reason,tf,events,d,pnl,exits,mask):
    m,cfg,variant,vm=row
    return {
        "model_id":m,"config_id":cfg,
        "zone_axes":[int((cfg>>(2*i))&3) for i in range(6)],
        "reward_risk_target":r31.R_MULTS[variant%len(r31.R_MULTS)],
        "holding_bars":r31.HOLD_BARS[variant//len(r31.R_MULTS)],
        "reason":reason,"validation":vm,
        "retrospective_2024_2026":r31.report_metrics(
            events,mask,tf,d,pnl,exits,variant,2024,2026),
        "retrospective_stress_extra_0_8_usd_oz":r31.report_metrics(
            events,mask,tf,d,pnl,exits,variant,2024,2026,
            stress=r31.STRESS_EXTRA),
        "selection_mask_sha256":hashlib.sha256(r31.r30.pack(mask)).hexdigest(),
    }

def diagnostic_reason(m,tf,threshold):
    if m["n"]<r31.VALMIN[tf]:return "INSUFFICIENT_VALIDATION_TRADES"
    if m["win_rate"] is None or m["win_rate"]<threshold:return "WIN_RATE_BELOW_FLOOR"
    if m["profit_factor"] is None or m["profit_factor"]<1.12:return "PROFIT_FACTOR_BELOW_1_12"
    if m["expectancy_usd_oz"] is None or m["expectancy_usd_oz"]<=0:return "EXPECTANCY_NOT_POSITIVE"
    annual=m["annual"]
    positive=sum(annual[str(yr)]["net_usd_oz"]>0 for yr in range(2021,2024))
    if positive<2:return "LESS_THAN_TWO_PROFITABLE_VALIDATION_YEARS"
    return "OTHER_GUARD"

def sweep(tf,model_start=0,models=32,caps=CONFIGS):
    if tf not in TF or model_start<0 or model_start+models>MODELS or not 1<=caps<=CONFIGS:
        raise ValueError("R31B_INVALID_SCOPE")
    d,source=r31.r30.load(tf)
    features=r31.r30.prepare(d)
    events=r31.events_from_closed_ohlc(d,features,tf)
    votes=r31.direction_votes(d,features,events)
    axes=r31.zone_axes(events)
    pnl,exits=r31.outcome_matrix(d,events)
    year=np.asarray([d.index[e["entry_index"]].year for e in events])
    exit_year=np.asarray([[d.index[exits[v,i]].year for i in range(len(events))]
                         for v in range(EXIT)],dtype=int)
    packed_axes=np.asarray([[r31.r30.pack(v) for v in row] for row in axes],dtype=np.uint8)
    # Exact feature/history maturity gates, never fill missing bars or future data.
    groups={}
    for v in range(EXIT):
        development=(year>=2012)&(year<=2020)&(exit_year[v]<=2020)
        validation=(year>=2021)&(year<=2023)&(exit_year[v]<=2023)
        groups[v]=(r31.r30.pack(development),
                   r31.r30.pack(development&(pnl[v]>0)),
                   r31.r30.pack(validation),
                   r31.r30.pack(validation&(pnl[v]>0)))
    pools={(v,kind):[] for v in range(EXIT) for kind in ("volume","precision")}
    evaluated=loose_eligible=0
    for model in range(model_start,model_start+models):
        packed_model=r31.r30.pack(votes[model])
        for start in range(0,caps,256):
            ids=np.arange(start,min(start+256,caps),dtype=np.uint32)
            masks=np.broadcast_to(packed_model,(len(ids),len(packed_model))).copy()
            for axis in range(6):
                np.bitwise_and(masks,packed_axes[axis,(ids>>(2*axis))&3],out=masks)
            for variant in range(EXIT):
                dv,dw,vv,vw=groups[variant]
                dn=np.bitwise_count(np.bitwise_and(masks,dv)).sum(axis=1)
                dk=np.bitwise_count(np.bitwise_and(masks,dw)).sum(axis=1)
                vn=np.bitwise_count(np.bitwise_and(masks,vv)).sum(axis=1)
                vk=np.bitwise_count(np.bitwise_and(masks,vw)).sum(axis=1)
                evaluated+=len(ids)
                good=np.flatnonzero((dn>=max(10,r31.DEVMIN[tf]//2))
                                     &(vn>=max(3,r31.VALMIN[tf]//2)))
                if not len(good):continue
                dwr=dk[good]/dn[good];vwr=vk[good]/vn[good]
                good=good[(dwr>=.46)&(vwr>=.50)]
                loose_eligible+=len(good)
                if not len(good):continue
                for kind in ("volume","precision"):
                    arr=top_indices(good,vn,vk,limit=6,kind=kind)
                    heap=pools[(variant,kind)]
                    for i in arr:
                        rr=vk[i]/vn[i]
                        lb=rr-1.96*np.sqrt(max(0.,rr*(1-rr))/vn[i])
                        key=((int(vn[i]),round(lb,7)) if kind=="volume"
                             else (round(lb,7),int(vn[i])))
                        shortlist_add(heap,key,(model,int(ids[i]),variant),256)
        if model%8==7:
            print(json.dumps({"stage":"R31B_DENSE_SCAN","tf":tf,"through_model":model,
                              "tested":evaluated,"loose_eligible":loose_eligible}),flush=True)

    picked=set()
    for heap in pools.values():
        for row in heap:
            picked.add((row[1],row[2],row[3]))
    # All finalists evaluated with true no-overlap, realistic stop-first,
    # 2021-2023 only. This final step is bounded, not all raw combos.
    full=[]
    for model,cfg,variant in sorted(picked):
        mask=votes[model].copy()
        for axis in range(6):mask &= axes[axis][(cfg>>(2*axis))&3]
        m=r31.report_metrics(events,mask,tf,d,pnl,exits,variant,2021,2023)
        if m["n"]>=max(3,r31.VALMIN[tf]//2):
            full.append((model,cfg,variant,m,mask))
    tiers={}
    for label,floor in (("volume_55",.55),("precision_60",.60)):
        passes=[x for x in full if r31._passes(x[3],tf,floor)]
        passes.sort(key=lambda x:(x[3]["n"],x[3]["wilson_lower95"],
                                   x[3]["profit_factor"] or 0),reverse=True)
        # Diagnostics: largest valid sample and best trade count satisfying
        # raw win-rate floor even if expectancy or year consistency fail.
        frequency=sorted(full,key=lambda x:x[3]["n"],reverse=True)
        winfloor=sorted((x for x in full if x[3]["n"]>=r31.VALMIN[tf]
                         and x[3]["win_rate"] is not None
                         and x[3]["win_rate"]>=floor),
                        key=lambda x:(x[3]["n"],x[3]["profit_factor"] or 0),
                        reverse=True)
        viable=sorted((x for x in full if x[3]["n"]>=r31.VALMIN[tf]
                         and x[3]["net_usd_oz"]>0
                         and x[3]["profit_factor"] is not None
                         and x[3]["profit_factor"]>=1.12),
                       key=lambda x:x[3]["n"],reverse=True)
        def serialize(x):
            model,cfg,variant,m,mask=x
            return annotated((model,cfg,variant,m),diagnostic_reason(m,tf,floor),
                             tf,events,d,pnl,exits,mask)
        tiers[label]={
            "pass":bool(passes),"qualifying":len(passes),
            "largest_passed":list(map(serialize,passes[:4])),
            "largest_win_floor_but_failed_other_gates":list(map(
                serialize,[x for x in winfloor if not r31._passes(x[3],tf,floor)][:2])),
            "largest_positive_pf_but_failed_other_gates":list(map(
                serialize,[x for x in viable if not r31._passes(x[3],tf,floor)][:2])),
            "largest_sample_regardless_of_profit":list(map(serialize,frequency[:1])),
        }
    report={
        "contract":"RIZAN_R31B_DENSE_COVERAGE_AUDIT_V1",
        "tf":tf,"source":r31.r30.SOURCE[tf],"source_shard_sha256":source,
        "model_start":model_start,"direction_models":models,
        "zone_configs":caps,"exit_variants":EXIT,
        "expected_evaluations":models*caps*EXIT,
        "actual_evaluations":evaluated,
        "source_events":len(events),"loose_packed_prequalifications":loose_eligible,
        "exact_validated_candidates":len(full),
        "data_first":d.index[0].isoformat(),"data_last":d.index[-1].isoformat(),
        "tiers":tiers,
        "scope":"SAME_R31_MODELS_MORE_COMPLETE_VALIDATION_SCREEN_NOT_INDEPENDENT_CONFIRMATION",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"frozen_model_parity":False,
        "limitations":[
            "R31B repeats R31 price/zone/direction family: NOT independent discovery",
            "Dense 2021-23 validation screening compounds multiple testing bias",
            "2024-26 retrospective evaluation is not pristine forward holdout",
            "Session-filtered Dukascopy H1/H4 vs HistData D1/W1; not cTrader FP Markets identical pricing",
            "OHLC cannot reproduce M5/M15 first-touch or intrabar fills; stop-first bar convention",
            "Net USD/oz costs assumed $0.70; real spreads/slippage/rollover unverified",
            "No trading permission, no Frozen V1 modification, no ForexScanner model promotion",
        ]
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/f"r31b-{tf}-models-{model_start}.json").write_text(
        json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R31B_DONE","tf":tf,"model_start":model_start,
        "tested":evaluated,"eligible":loose_eligible,"exact":len(full),
        "tiers":{tier:{"pass":v["pass"],"n_candidates":v["qualifying"],
                       "best_val_n":v["largest_passed"][0]["validation"]["n"]
                            if v["largest_passed"] else None}
                 for tier,v in tiers.items()}}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=TF,required=True)
    p.add_argument("--model-start",type=int,default=0)
    p.add_argument("--models",type=int,default=32)
    p.add_argument("--zone-configs",type=int,default=CONFIGS)
    a=p.parse_args()
    sweep(a.tf,a.model_start,a.models,a.zone_configs)

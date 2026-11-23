"""RIZAN R29: pre-registered, selective BUY/SELL direction research.

Goal: >60% per side with nontrivial support, OOS-like annual walk-forward
and positive hypothetical 0.70 USD/oz close-to-close net expectancy.
Research only; earlier evaluation years 2024-2026 have been viewed during
R1-R28 and are NOT an untouched holdout. No broker orders or dashboard writes.

At a FULLY CLOSED TF candle predict NEXT candle close-to-close sign.
Train on historical candles whose next-bar labels matured BEFORE validation;
select thresholds/regime with the immediate preceding year's labels;
evaluate strictly subsequent year's candles. Each TF/side has independent
family/model/threshold/regime; conflicting simultaneous heads => WAIT.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from r14_multitimeframe_direction import load_tf
from r16_direction_complexity import features
from r21_horizon_specialists import price_specialist
from r10_million import wilson

ROOT=Path("artifacts")
ROOT.mkdir(exist_ok=True)
NAME={"1h":"H1","4h":"H4","1D":"D1","1W":"W1"}
MINVAL={"1h":100,"4h":45,"1D":20,"1W":8}
MINEVAL={"1h":120,"4h":60,"1D":35,"1W":14}
MINTRAIN={"1h":1600,"4h":500,"1D":400,"1W":95}
COST_USD_OZ=0.70
CUTS=(0.50,0.53,0.56,0.60,0.64,0.68)
TESTYEARS={"1h":(2024,2025,2026),"4h":(2024,2025,2026),
           "1D":(2023,2024,2025,2026),"1W":(2023,2024,2025,2026)}
ENGINES=("ridge","hgb")
STRATEGY="R29_V1_PREDECLARED_20261123"


def feature_groups(tf,d,z):
    """Price-only feature sets. No hindsight macro revisions or future bars."""
    if tf in ("1h","4h"):
        f,sets=price_specialist(d,z,tf)
        if tf=="1h":
            chosen=("intraday_price","session_interaction")
        else:
            chosen=("compact_structure","structure_context")
        return {key:f[sets[key]] for key in chosen}
    # D1 and W1: measured at completed candle close; no future labeling
    p=features(z).drop(columns=["hour_sin","hour_cos"],errors="ignore")
    c=d.c.astype(float)
    atr=z.atr14.replace(0,np.nan)
    r=np.log(c/c.shift(1))
    extras=pd.DataFrame({
        "ret1":r,
        "ret3":np.log(c/c.shift(3)),
        "ret8":np.log(c/c.shift(8)),
        "return_acceleration":r.rolling(3).mean()-r.rolling(12).mean(),
        "vol_5_20":r.rolling(5).std()/r.rolling(20).std().replace(0,np.nan),
        "atr_3_12":atr.rolling(3).mean()/atr.rolling(12).mean().replace(0,np.nan),
        "close_position_8":(c-d.l.shift(1).rolling(8).min())/
             (d.h.shift(1).rolling(8).max()-d.l.shift(1).rolling(8).min()).replace(0,np.nan),
    },index=d.index)
    return {"technical":p,"technical_regime":pd.concat([p,extras],axis=1)}


def gates(tf,z,times,side):
    """Predeclared causal filters; avoid conditioning on future price."""
    s=1 if side=="BUY" else -1
    atr=z.atr14.replace(0,np.nan)
    trend=(z.ema8-z.ema21)/atr
    vol=z.atr_rank
    gate={
        "all":np.ones(len(z),dtype=bool),
        "trend_follow":np.asarray(s*trend>0,bool),
        "countertrend":np.asarray(s*trend<0,bool),
        "vol_high":np.asarray(vol>=.6,bool),
        "vol_low":np.asarray(vol<=.4,bool),
        "trend_highvol":np.asarray((s*trend>0)&(vol>=.6),bool),
    }
    if tf=="1h":
        lh=times.tz_convert("Europe/London").hour
        ny=times.tz_convert("America/New_York").hour
        gate["london_ny"]=np.asarray(((lh>=8)&(lh<17))|((ny>=8)&(ny<12)),bool)
    if tf=="4h":
        lh=times.tz_convert("Europe/London").hour
        gate["london"]=np.asarray((lh>=8)&(lh<17),bool)
    return gate


def model_factory(name):
    if name=="ridge":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(C=0.05,max_iter=600,random_state=29))
    if name=="hgb":
        return HistGradientBoostingClassifier(
            max_iter=75,max_depth=2,max_leaf_nodes=7,learning_rate=0.06,
            l2_regularization=15,early_stopping=False,random_state=29)
    raise ValueError("R29_UNKNOWN_MODEL")


def stats(y,mask,side,base=None):
    mask=np.asarray(mask,dtype=bool)
    n=int(mask.sum())
    k=int(np.count_nonzero(y[mask]==(1 if side=="BUY" else 0)))
    correct=k/n if n else None
    out={
        "n":n,"correct":k,"accuracy":round(correct,6) if n else None,
        "wilson_lower95":round(float(wilson(k,n)),6) if n else None,
        "coverage":round(n/max(1,len(y)),6),
    }
    if base is not None and n:
        # Next-bar close-to-close gross difference, NOT fill at broker bid/ask.
        delta=base["next_close"][mask]-base["reference_close"][mask]
        signed=delta*(1 if side=="BUY" else -1)
        out.update({
            "gross_mean_usd_oz":round(float(signed.mean()),4),
            "net_mean_after_assumed_cost_usd_oz":round(float(signed.mean()-COST_USD_OZ),4),
            "positive_net_estimate":bool(signed.mean()>COST_USD_OZ),
            "mfe_ge_10_usd_fraction":round(float(np.mean(
                (base["next_high"][mask]-base["reference_close"][mask]
                 if side=="BUY" else base["reference_close"][mask]-base["next_low"][mask])>=10
            )),5),
        })
    return out


def select_side(y_val,prob_val,gate_val,min_val,side):
    best=None
    for threshold,gn in itertools.product(CUTS,gate_val):
        active=(prob_val>=threshold)&gate_val[gn]
        m=stats(y_val,active,side)
        if m["n"]<min_val:continue
        rank=(m["accuracy"]>=.60, m["wilson_lower95"],
              m["coverage"],-threshold)
        if best is None or rank>best[0]:
            best=(rank,{"threshold":threshold,"gate":gn,
                        "validation":m})
    return best


def split_masks(times,valid,year,window=6):
    """Causal label-maturity embargo at train->validation->test boundary."""
    teststart=pd.Timestamp(f"{year}-01-01",tz="UTC")
    valstart=teststart-pd.DateOffset(years=1)
    trainstart=valstart-pd.DateOffset(years=window)
    testend=teststart+pd.DateOffset(years=1)
    mature=pd.Series(times).shift(-1)
    # The original row represents a completed candle, but its NEXT candle
    # label must mature within the same allowed train/validation window.
    train=valid&(times>=trainstart)&(times<valstart)&(mature<valstart).to_numpy()
    val=valid&(times>=valstart)&(times<teststart)&(mature<teststart).to_numpy()
    test=valid&(times>=teststart)&(times<testend)&(mature<testend).to_numpy()
    if np.any(train&val) or np.any(train&test) or np.any(val&test):
        raise AssertionError("R29_OVERLAPPING_SPLITS")
    return train,val,test


def fold(tf,year,d,z,y,base_valid,times,groups,gate_sets):
    annual={"year":year,"sides":{},"n_test":0,"coverage":0,
            "conflicts":0,"wait":None}
    preds={}
    for side in ("BUY","SELL"):
        choices=[]
        head=1 if side=="BUY" else 0
        for group,frame in groups.items():
            x=frame.to_numpy(dtype=float)
            valid=base_valid & np.isfinite(x).all(axis=1)
            tr,va,te=split_masks(times,valid,year)
            if (tr.sum()<MINTRAIN[tf] or va.sum()<2*MINVAL[tf]
                    or te.sum()<MINVAL[tf] or np.unique(y[tr]).size!=2):
                continue
            masks=gate_sets[side]
            vg={k:np.asarray(v[va],dtype=bool) for k,v in masks.items()}
            for name in ENGINES:
                m=model_factory(name)
                m.fit(x[tr],(y[tr]==head).astype("int8"))
                pv=m.predict_proba(x[va])[:,1]
                selected=select_side(y[va],pv,vg,MINVAL[tf],side)
                if selected is None:continue
                rank,sel=selected
                choices.append((rank,sel,group,name,m,x,te,masks))
        if not choices:
            annual["sides"][side]={"selected":None,"reason":"NO_VALIDATED_CANDIDATE"}
            continue
        rank,chosen,group,name,model,x,te,masks=max(
            choices,key=lambda a:(a[0],a[2],a[3]))
        testprob=model.predict_proba(x[te])[:,1]
        gate=np.asarray(masks[chosen["gate"]][te],bool)
        triggered=np.asarray((testprob>=chosen["threshold"])&gate,bool)
        # Label of every test candle is included only to score it afterwards.
        # No peeking while selecting configuration or deciding a mask.
        ix=np.flatnonzero(te)
        preds[side]=(ix,triggered)
        annual["sides"][side]={
            "selected":{"model":name,"group":group,
                        "threshold":chosen["threshold"],
                        "gate":chosen["gate"],"selection":chosen["validation"]},
            "pre_conflict":stats(y[te],triggered,side),
        }
    return annual,preds


def run(tf):
    if tf not in NAME:raise ValueError("R29_UNSUPPORTED_TF")
    d,z,_,y,base_valid,times=load_tf(tf)
    groups=feature_groups(tf,d,z)
    gate_sets={side:gates(tf,z,times,side) for side in ("BUY","SELL")}
    years=TESTYEARS[tf]
    parts=[];totals={side:[] for side in ("BUY","SELL")}
    duplicate_guard=set()
    for year in years:
        row,preds=fold(tf,year,d,z,y,base_valid,times,groups,gate_sets)
        te=np.flatnonzero((times>=pd.Timestamp(f"{year}-01-01",tz="UTC"))
                      &(times<pd.Timestamp(f"{year+1}-01-01",tz="UTC"))
                      &base_valid)
        # Join independent heads over the SAME candle index.
        b=np.zeros(len(d),bool);s=np.zeros(len(d),bool)
        for side,dest in (("BUY",b),("SELL",s)):
            if side not in preds:continue
            ids,flags=preds[side]
            dest[ids]=flags
        clash=b&s
        b&=~clash
        s&=~clash
        row["conflicts"]=int(clash.sum())
        row["n_test"]=int(len(te))
        row["wait"]=int(len(te)-np.count_nonzero(b[te]|s[te]))
        row["coverage"]=round(float(np.mean(b[te]|s[te])) if len(te) else 0.,6)
        for side,selected in (("BUY",b),("SELL",s)):
            ref=d.c.to_numpy(dtype=float)
            base={"reference_close":ref,
                  "next_close":d.c.shift(-1).to_numpy(dtype=float),
                  "next_high":d.h.shift(-1).to_numpy(dtype=float),
                  "next_low":d.l.shift(-1).to_numpy(dtype=float)}
            report=stats(y[te],selected[te],side,
                         base={k:v[te] for k,v in base.items()})
            row["sides"].setdefault(side,{})["evaluated"]=report
            totals[side].append((y[te],selected[te],{k:v[te] for k,v in base.items()}))
        parts.append(row)
        if year in duplicate_guard:raise ValueError("R29_DUPLICATE_YEAR")
        duplicate_guard.add(year)
        print(json.dumps({"tf":NAME[tf],"year":year,
                          "sides":{k:v.get("evaluated") for k,v in row["sides"].items()},
                          "coverage":row["coverage"]}),flush=True)
    aggregate={}
    for side,observations in totals.items():
        yy=np.concatenate([t[0] for t in observations])
        activated=np.concatenate([t[1] for t in observations])
        base={k:np.concatenate([t[2][k] for t in observations])
              for k in observations[0][2]}
        aggregate[side]=stats(yy,activated,side,base=base)
    evaluated=sum(p["n_test"] for p in parts)
    covered=sum(p["n_test"]-p["wait"] for p in parts)
    years_with_signals={
        side:sum(p["sides"].get(side,{}).get("evaluated",{}).get("n",0)>=
                 max(5,MINVAL[tf]//4) for p in parts)
        for side in ("BUY","SELL")
    }
    passed=bool(
        all(aggregate[side]["n"]>=MINEVAL[tf]
            and aggregate[side]["accuracy"] is not None
            and aggregate[side]["accuracy"]>.60
            and aggregate[side].get("positive_net_estimate",False)
            and years_with_signals[side]>=2
            for side in ("BUY","SELL"))
        and covered/max(1,evaluated)>=.04)
    report={
        "version":STRATEGY,"tf":NAME[tf],
        "goal":">60% out-of-fold historical BUY and SELL independently",
        "target":"next CLOSED candle close-to-close direction",
        "source": "R10 HistData 2019-2026" if tf in ("1h","4h")
                  else "R9.8 derived daily OHLC 2012-2026",
        "years":list(years),"total_eligible":evaluated,
        "policy_selection":"label-matured earlier training and previous-year selection only",
        "model_types":list(ENGINES),"thresholds":list(CUTS),
        "feature_groups":list(groups),
        "cost_scenario_usd_oz":COST_USD_OZ,
        "min_validation_per_side":MINVAL[tf],
        "min_aggregate_per_side":MINEVAL[tf],
        "aggregate":aggregate,
        "annual":parts,
        "coverage":round(covered/max(1,evaluated),6),
        "stable_years_with_support":years_with_signals,
        "passes_all_predeclared_gates":passed,
        "research_only":True,"live_permission":False,"execution_authority":False,
        "limitations":[
            "Historical 2024-2026 folds were already inspected in R1-R28; not a pristine forward test",
            "No external FP Markets bid/ask verified; 0.70 USD/oz is an assumed cost scenario, not a measured spread",
            "Direction accuracy is not trade profitability or fill-adjusted execution",
            "SMC/ICT features are quantitative proxies from completed OHLC, not verified institutional order flow",
            "No macro surprises/DXY/COT included until independent point-in-time availability is audited",
            "Threshold/gate chosen from previous validation year; risk of multiple-testing remains",
            "Research results are NOT used to alter Frozen V1 or ForexScanner live model",
        ],
    }
    target=ROOT/f"r29-direction-{tf}.json"
    target.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"tf":NAME[tf],"passed":passed,
                      "aggregate":aggregate,"coverage":report["coverage"],
                      "file":str(target)}),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--tf",required=True,choices=list(NAME))
    run(parser.parse_args().tf)

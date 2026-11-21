"""RIZAN R15 — direction-first tournament: 18,432 independently defined rule vectors.
Four independent timeframe models H1 H4 D1 W1. NO zone/entry prediction.
All signals use completed-candle features. Data snapshots via R10/R9.8 artifacts.
Statistical caution: 2023-26 evaluation has been inspected in prior studies,
thus is NOT pristine holdout. Screening 4,608 candidates per timeframe
amplifies multiple-testing bias even with fixed chronological partitions.
"""
from __future__ import annotations
import argparse,itertools,hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from r10_million import load,ohlc_indicators,wilson
from r102_calibrated import context
from r14_multitimeframe_direction import load_tf,split,causal_test
OUT=Path("artifacts");OUT.mkdir(exist_ok=True)
FAMILIES=[
 "ema_cross","roc3","roc8","macd_hist","rsi14","rsi7","directional_index",
 "candle_location","candle_body","body3","liquidity_sweep","range_breakout",
 "discount_reversal","ema_mean_reversion","price_efficiency","range_displacement"
]
SMOOTH=[1,3,5]
ORIENTATION=["momentum","contrarian"]
THRESHOLDS=[0.12,0.30,0.55]
REGIMES=["any","adx_trend","adx_range","high_volatility"]
CONTEXT=["none","local_trend","higher_trend","dual_trend"]
SPACE=len(FAMILIES)*len(SMOOTH)*len(ORIENTATION)*len(THRESHOLDS)*len(REGIMES)*len(CONTEXT)
assert SPACE==4608
def features(z):
    c=z.c.to_numpy(float)
    atr=z.atr14.to_numpy(float)
    atr=np.where(np.isfinite(atr)&(atr>1e-8),atr,np.nan)
    def col(k):return z[k].to_numpy(float)
    rt=col("rangeratio")
    raw=[
      (col("ema8")-col("ema21"))/atr,
      col("roc3")*c/(atr*3),
      col("roc8")*c/(atr*6),
      col("macdh")/atr*4,
      (col("rsi14")-50)/15,
      (col("rsi7")-50)/15,
      col("di")/25,
      col("clv"),
      col("body"),
      col("b3")*2,
      col("sweep5")*1.5,
      col("break8")*1.2,
      (0.5-col("discount"))*2,
      (col("ema21")-c)/atr,
      col("eff3"),
      col("clv")*np.clip(rt,0,3),
    ]
    return [np.clip(v,-2,2) for v in raw]
def static_regimes(z):
    return [
      np.ones(len(z),bool),
      (z.adx14>20).fillna(False).to_numpy(bool),
      (z.adx14<20).fillna(False).to_numpy(bool),
      (z.atr_rank>.55).fillna(False).to_numpy(bool)]
def contexts(z,tf):
    local=np.sign((z.ema8-z.ema21).to_numpy(float))
    if tf in ("1h","4h"):
        high=np.sign(z.d1_mom.to_numpy(float))
    else:
        high=np.sign(z.roc8.to_numpy(float))
    return local,high
def signals(score,smooth,orient,threshold,regime,context,local,high,base):
    sig=base[smooth]
    if orient: sig=-sig
    buy=(sig>threshold)&regime
    sell=(sig<(-threshold))&regime
    if context in (1,3):
        buy &= local>0;sell &= local<0
    if context in (2,3):
        buy &= high>0;sell &= high<0
    return buy,sell
def smooth_cache(z):
    raw=features(z)
    return [[pd.Series(a).rolling(win,min_periods=win).mean().to_numpy(float)
             for win in SMOOTH] for a in raw]
def score(y,buy,sell,mask):
    nmask=int(mask.sum())
    a=buy&mask;b=sell&mask
    nb=int(a.sum());ns=int(b.sum())
    kb=int((y[a]==1).sum());ks=int((y[b]==0).sum())
    return {
      "BUY":{"n":nb,"correct":kb,"accuracy":round(kb/nb,6) if nb else None,
             "wilson_lower95":round(wilson(kb,nb),6) if nb else None},
      "SELL":{"n":ns,"correct":ks,"accuracy":round(ks/ns,6) if ns else None,
             "wilson_lower95":round(wilson(ks,ns),6) if ns else None},
      "WAIT":nmask-nb-ns,
      "coverage":round((nb+ns)/max(1,nmask),6)}
def rule(z,tf,cfg):
    fi,wi,oi,ti,ri,ci=cfg
    base=smooth_cache(z)[fi]
    reg=static_regimes(z)[ri]
    lo,hi=contexts(z,tf)
    return signals(None,wi,oi,THRESHOLDS[ti],reg,ci,lo,hi,base)
def audit_selected(d,z,tf,cfg,valid):
    eligible=np.flatnonzero(valid&(z.index.year>=2019))
    check=eligible[np.linspace(0,len(eligible)-1,min(len(eligible),12),dtype=int)]
    orig_b,orig_s=rule(z,tf,cfg)
    diffs=[]
    h1=load("1h") if tf in ("1h","4h") else None
    for i in check:
        p=ohlc_indicators(d.iloc[:i+1])
        if h1 is not None:
            now=z.index[i]+pd.Timedelta(hours=1 if tf=="1h" else 4)
            h1prior=h1.loc[(h1.index+pd.Timedelta(hours=1))<=now]
            context(p,h1prior,1 if tf=="1h" else 4)
        u,v=rule(p,tf,cfg)
        if bool(u[-1])!=bool(orig_b[i]) or bool(v[-1])!=bool(orig_s[i]):
            diffs.append(str(z.index[i]))
    return {"checks":len(check),"mismatch":diffs,"pass":not diffs}
def run(tf):
    d,z,_,y,valid,_=load_tf(tf)
    train,cal,val,test,bounds=split(tf,z.index,valid)
    first=causal_test(tf,d,z,valid)
    if first["status"]!="PASS":raise RuntimeError("CAUSAL INPUT FAIL "+str(first))
    # Selection uses TRAIN + VALIDATION ONLY; no test outcomes until winner frozen.
    raw=smooth_cache(z)
    regimes=static_regimes(z)
    local,high=contexts(z,tf)
    minval={"1h":50,"4h":25,"1D":15,"1W":5}[tf]
    mintrain={"1h":300,"4h":120,"1D":90,"1W":25}[tf]
    shortlisted=[];eligible=0;total=0
    for fi in range(len(FAMILIES)):
      for wi,oi,ti,ri,ci in itertools.product(range(3),range(2),range(3),range(4),range(4)):
        total+=1
        cfg=[fi,wi,oi,ti,ri,ci]
        b,s=signals(None,wi,oi,THRESHOLDS[ti],regimes[ri],ci,local,high,raw[fi])
        tr=score(y,b,s,train)
        va=score(y,b,s,val)
        ok=(min(tr["BUY"]["n"],tr["SELL"]["n"])>=mintrain and
            min(va["BUY"]["n"],va["SELL"]["n"])>=minval)
        if not ok:continue
        eligible+=1
        lowertrain=min(tr["BUY"]["wilson_lower95"],tr["SELL"]["wilson_lower95"])
        lowerval=min(va["BUY"]["wilson_lower95"],va["SELL"]["wilson_lower95"])
        quality=round(min(lowertrain,lowerval),8)
        shortlisted.append({"cfg":cfg,
                "family":FAMILIES[fi],"smoothing":SMOOTH[wi],
                "orientation":ORIENTATION[oi],"threshold":THRESHOLDS[ti],
                "regime":REGIMES[ri],"context":CONTEXT[ci],
                "training":tr,"validation":va,"selection_quality":quality})
    shortlisted.sort(key=lambda x:(x["selection_quality"],x["validation"]["coverage"]),reverse=True)
    report={"version":"R15","timeframe":tf,"candidates_evaluated":total,
      "eligible_development_candidates":eligible,
      "search_definition":"16 distinct price-signal families x 3 smoothing windows x 2 orientations x 3 signal thresholds x 4 volatility/trend regimes x 4 directional contexts",
      "periods":bounds,
      "label":"next completed candle close vs current completed candle close",
      "sample_sizes":{"train":int(train.sum()),"calibration":int(cal.sum()),
           "validation":int(val.sum()),"evaluation":int(test.sum())},
      "upstream_causality":first,
      "candidates_selected_only_on_training_and_validation":shortlisted[:10],
      "no_zone_research":True,"live_orders_allowed":False,
      "limitations":["The 2023-2026 historical evaluation has already been inspected by prior research; not a pristine holdout",
       "Multiple hypothesis testing of 4,608 vectors per timeframe inflates sample discoveries",
       "No DXY, yields or COT point-in-time feed in this experiment",
       "No trading costs or executable entry claims: direction only",
       "Weekly sample counts are small, annual win rates often insufficient to generalize"]}
    if shortlisted:
        winner=shortlisted[0]
        cfg=winner["cfg"]
        proof=audit_selected(d,z,tf,cfg,valid)
        if not proof["pass"]:raise RuntimeError("SELECTED PREFIX INVARIANCE FAILED "+str(proof))
        b,s=rule(z,tf,cfg)
        ev=score(y,b,s,test)
        report["selected_prefix_audit"]=proof
        report["evaluation"]=ev
        report["annual_evaluation"]={str(year):score(y,b,s,test&(z.index.year==year))
              for year in sorted(set(z.index.year[test]))}
        report["base_rates"]={"always_BUY":round(float(y[test].mean()),6),
          "always_SELL":round(float(1-y[test].mean()),6)}
        nmin={"1h":100,"4h":100,"1D":50,"1W":15}[tf]
        report["meets_60pct_both_sides_observed"]=bool(
           min(ev["BUY"]["n"],ev["SELL"]["n"])>=nmin and
           ev["BUY"]["wilson_lower95"]>=.60 and ev["SELL"]["wilson_lower95"]>=.60)
    else:
        report["selected_prefix_audit"]=None
        report["evaluation"]=None
        report["annual_evaluation"]={}
        report["meets_60pct_both_sides_observed"]=False
    p=OUT/f"r15-direction-{tf}.json"
    p.write_text(json.dumps(report,indent=2))
    print(json.dumps({"phase":"complete","timeframe":tf,"total":total,"eligible":eligible,
     "best":shortlisted[0] if shortlisted else None,
     "evaluation":report["evaluation"],
     "annual_evaluation":report["annual_evaluation"],
     "pass":report["meets_60pct_both_sides_observed"]}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--tf",required=True,choices=("1h","4h","1D","1W"))
    run(p.parse_args().tf)

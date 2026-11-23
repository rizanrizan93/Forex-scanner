"""R29.3 conditional ATR-normalized forward-return regression (research only).

Unlike R29.2's P(direction), learn the next closed candle's expected return
divided by ATR at the CURRENT candle. A separate positive-magnitude or
negative-magnitude trigger, combined with causal SMC/ICT-like setup gates,
selects BUY and SELL independently on the previous validation year.

The H4 SELL 2026 directional precision exceeded 60% in some older
configurations yet its expected USD/oz return was negative. This tests the
predeclared hypothesis that modeling tail magnitude improves trade quality.
EVALUATION YEARS WERE ALREADY INSPECTED; never call this a blind holdout.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import r29_direction60_walkforward as base
import r292_magnitude_regime_expansion as r292

CONFIG={
    "precision": {
        "thresholds":(.07,.12,.18,.25,.35,.50),
        "models":("ridge","hgb_mean","hgb_median"),
        "min_val":{"1h":70,"4h":32,"1D":17,"1W":8},
        "min_support_halves":.20,
        "require_net_positive":True,
    },
    "coverage": {
        "thresholds":(.02,.05,.09,.14,.22,.32),
        "models":("ridge","hgb_mean","hgb_median"),
        "min_val":{"1h":100,"4h":45,"1D":21,"1W":9},
        "min_support_halves":.12,
        "require_net_positive":False,
    },
}
VARIANT="precision"


def factory(name):
    if name=="ridge":
        return make_pipeline(StandardScaler(),
                             Ridge(alpha=25.0,random_state=293))
    kw={"max_iter":85,"max_depth":2,"max_leaf_nodes":7,
        "learning_rate":.05,"l2_regularization":18.,
        "early_stopping":False,"random_state":293}
    if name=="hgb_mean":
        return HistGradientBoostingRegressor(loss="squared_error",**kw)
    if name=="hgb_median":
        return HistGradientBoostingRegressor(loss="absolute_error",**kw)
    raise ValueError("R293_UNKNOWN_REGRESSOR")


def training_target(d,z):
    """Label uses next close; predictor features see only completed current bar."""
    atr=z.atr14.replace(0,np.nan).to_numpy(float)
    close=d.c.to_numpy(float)
    y=(d.c.shift(-1).to_numpy(float)-close)/atr
    # Winsorization of the TARGET must use fixed, prespecified ATR units
    # (no fit to the held-out year or global future quantile).
    return np.clip(y,-6.,6.)


def val_stats(labels,signal,side,delta,half,min_support):
    signal=np.asarray(signal,bool)
    if int(signal.sum())<min_support:
        return None
    score=base.stats(labels,signal,side)
    signed=(1 if side=="BUY" else -1)*delta[signal]
    net=signed-base.COST_USD_OZ
    halves=[int(np.sum(signal&(half==q))) for q in (1,2)]
    min_per_half=int(np.ceil(min_support*CONFIG[VARIANT]["min_support_halves"]))
    supported=min(halves)>=min_per_half
    report={
        **score,
        "validation_mean_net_usd_oz":round(float(net.mean()),5),
        "validation_p10_net_usd_oz":round(float(np.quantile(net,.10)),5),
        "validation_median_net_usd_oz":round(float(np.median(net)),5),
        "half_year_counts":halves,
        "half_year_supported":supported,
    }
    return report


def ranking(metric):
    """Comparison never consumes evaluation-period outcomes."""
    positive=metric["validation_mean_net_usd_oz"]>0
    qualifying=metric["accuracy"]>=.60 and metric["half_year_supported"]
    tail=metric["validation_p10_net_usd_oz"]
    if CONFIG[VARIANT]["require_net_positive"]:
        return (qualifying and positive,positive,metric["half_year_supported"],
                metric["wilson_lower95"],metric["validation_mean_net_usd_oz"],
                tail,metric["coverage"])
    return (qualifying,metric["half_year_supported"],positive,
            metric["wilson_lower95"],metric["coverage"],
            metric["validation_mean_net_usd_oz"])


def fold(tf,year,d,z,y,base_valid,times,groups,gate_sets):
    annual={"year":year,"sides":{},"n_test":0,
            "coverage":0,"conflicts":0,"wait":None}
    preds={}
    target=training_target(d,z)
    close=d.c.to_numpy(float)
    delta=d.c.shift(-1).to_numpy(float)-close
    half=np.where(times.month<=6,1,2)
    preset=CONFIG[VARIANT]
    for side in ("BUY","SELL"):
        eligible=[]
        sign=1 if side=="BUY" else -1
        for name,f in groups.items():
            X=f.to_numpy(float)
            valid=(base_valid&np.isfinite(X).all(axis=1)
                   &np.isfinite(target)&np.isfinite(delta))
            tr,va,te=base.split_masks(times,valid,year)
            minimum=preset["min_val"][tf]
            if (tr.sum()<base.MINTRAIN[tf] or va.sum()<minimum*2
                    or te.sum()<minimum):continue
            gates={k:np.asarray(v[va],bool)
                   for k,v in gate_sets[side].items()}
            for family in preset["models"]:
                m=factory(family)
                m.fit(X[tr],target[tr])
                pred=m.predict(X[va])
                for threshold,gname in itertools.product(
                    preset["thresholds"],gates
                ):
                    mask=(sign*pred>=threshold)&gates[gname]
                    metric=val_stats(y[va],mask,side,delta[va],half[va],minimum)
                    if metric is None:continue
                    rank=ranking(metric)
                    eligible.append((rank,name,family,threshold,gname,m,X,te,
                                     gate_sets[side],metric))
        if not eligible:
            annual["sides"][side]={
                "selected":None,"reason":"NO_VALIDATED_RETURN_MAGNITUDE_HEAD"
            }
            continue
        rank,group,family,threshold,gname,model,X,te,gates,metric=max(
            eligible,key=lambda x:(x[0],x[1],x[2],-x[3],x[4]))
        p=model.predict(X[te])
        active=((sign*p)>=threshold)&np.asarray(gates[gname][te],bool)
        preds[side]=(np.flatnonzero(te),np.asarray(active,bool))
        annual["sides"][side]={
            "selected":{
                "model":family,"group":group,
                "atr_threshold":float(threshold),"gate":gname,
                "validation":metric,"selection_rank":list(rank),
            },
            "pre_conflict":base.stats(y[te],active,side),
        }
    return annual,preds


def run(tf,variant):
    global VARIANT
    if variant not in CONFIG:raise ValueError("R293_UNKNOWN_VARIANT")
    original=(
        base.feature_groups,base.gates,base.fold,
        base.MINVAL,base.ENGINES,base.CUTS,base.STRATEGY,
    )
    VARIANT=variant
    try:
        base.feature_groups=r292.feature_groups
        base.gates=r292.gates
        base.fold=fold
        base.MINVAL={**base.MINVAL,**CONFIG[variant]["min_val"]}
        base.ENGINES=CONFIG[variant]["models"]
        base.CUTS=CONFIG[variant]["thresholds"]
        base.STRATEGY="R29_3_ATR_MAGNITUDE_"+variant.upper()+"_20261123"
        result=base.run(tf)
        result["variant"]="R29.3 "+variant
        result["training_target"]="next close-minus-close in current ATR units, winsorized +/-6"
        result["selection_objective"]="earlier-year direction precision and estimated payoff after assumed $0.70/oz cost"
        result["limitations"].append(
            "Target winsorized at fixed ±6 ATR, never with future fold statistics."
        )
        result["limitations"].append(
            "This is a SECOND adaptive challenger after inspecting R29.2, "
            "not a fresh blind evaluation. Forward observation still required."
        )
        dest=base.ROOT/f"r293-{variant}-{tf}.json"
        dest.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
        print(json.dumps({
            "variant":"R29.3 "+variant,"tf":base.NAME[tf],
            "passed":result["passes_all_predeclared_gates"],
            "coverage":result["coverage"],"aggregate":result["aggregate"],
            "receipt":str(dest),
        }),flush=True)
        return result
    finally:
        (base.feature_groups,base.gates,base.fold,
         base.MINVAL,base.ENGINES,base.CUTS,base.STRATEGY)=original


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=("1h","4h","1D"),required=True)
    p.add_argument("--variant",choices=list(CONFIG),required=True)
    a=p.parse_args()
    run(a.tf,a.variant)

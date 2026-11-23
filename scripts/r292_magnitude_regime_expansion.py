"""RIZAN R29.2: magnitude-aware, regime-conditioned BUY/SELL side experts.

Research continuation of R29.1 H4 BUY 199/332 (59.94%), not an approved edge.
Two *fixed before running this version* variants:
  precision: enforce validation profitability and half-year support in ranking,
  balanced: higher support/coverage and validation stability penalties.
All selection uses the immediately previous year only. 2024-2026 evaluation
labels are NEVER read to choose family, parameters, probability cut or filter.
As previously inspected dates, those folds are diagnostic, not pristine OOS.

The study reports direction accuracy, coverage, n, Wilson lower bound, assumed
0.70 USD/oz net candle-to-candle drift and annual stability. No FP Markets
spread is measured; no live execution, no cBot, no ForexScanner writes.
"""
from __future__ import annotations

import argparse
import itertools
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import r29_direction60_walkforward as base
import r291_event_structure_direction as event
from r21_horizon_specialists import price_specialist
from r16_direction_complexity import features as technical_features

BASE_MIN=dict(base.MINVAL)
CONFIG={
    "precision": {
        "cutoffs":(.54,.58,.62,.66,.70,.74,.78),
        "minimum":{"1h":75,"4h":35,"1D":17,"1W":8},
        "min_half_share":.20,
        "models":("ridge","hgb","extra"),
        "allow_neg_validation_net":False,
    },
    "balanced": {
        "cutoffs":(.50,.53,.56,.59,.62,.66,.70),
        "minimum":{"1h":110,"4h":45,"1D":20,"1W":9},
        "min_half_share":.10,
        "models":("ridge","hgb","extra"),
        "allow_neg_validation_net":True,
    }
}
PRESET="precision"
OLD_GATES=event.gates
OLD_FEATURES=event.feature_groups


def model_factory(name):
    if name=="ridge":
        return make_pipeline(StandardScaler(),
                 LogisticRegression(C=.025,max_iter=700,random_state=292))
    if name=="hgb":
        return HistGradientBoostingClassifier(
            max_iter=100,max_depth=2,max_leaf_nodes=9,
            learning_rate=.045,l2_regularization=20,
            early_stopping=False,random_state=292)
    if name=="extra":
        return ExtraTreesClassifier(
            n_estimators=110,max_depth=5,min_samples_leaf=30,
            max_features=.75,n_jobs=2,random_state=292)
    raise ValueError("R292_UNKNOWN_MODEL")


def feature_groups(tf,d,z):
    groups=OLD_FEATURES(tf,d,z)
    if tf in ("1h","4h"):
        frame,sets=price_specialist(d,z,tf)
        if tf=="4h":
            context=frame[sets["structure_context"]]
            short=frame[sets["compact_structure"]]
        else:
            context=frame[sets["session_interaction"]]
            short=frame[sets["intraday_price"]]
        # Causal prior-bar context — do not include incomplete H1/D1/W1.
        groups["cross_regime"]=(pd.concat([groups["event_geometry"],short],axis=1)
                               .loc[:,lambda x:~x.columns.duplicated()])
        groups["broad_context"]=(pd.concat([context,groups["event_geometry"]],axis=1)
                                .loc[:,lambda x:~x.columns.duplicated()])
    else:
        p=technical_features(z).drop(columns=["hour_sin","hour_cos"],errors="ignore")
        groups["technical_plus_events"]=pd.concat(
            [groups["event_geometry"],p],axis=1
        ).loc[:,lambda x:~x.columns.duplicated()]
    return groups


def gates(tf,z,times,side):
    g=OLD_GATES(tf,z,times,side)
    s=1 if side=="BUY" else -1
    atr=z.atr14.replace(0,np.nan)
    trend=(z.ema8-z.ema21)/atr
    # Two-sided, different continuation/reversal regimes: end-of-candle only.
    body=s*z.body
    wick=s*z.clv
    mom=s*z.roc3
    controlled={
        "trend_strong":(s*trend>.20)&(z.adx14>=18),
        "trend_wide":(s*trend>.0)&(z.adx14>=15),
        "trend_reject":(s*trend>.0)&(s*z.sweep5>0),
        "trend_compress":(s*trend>.0)&(z.bbwidth<z.bbmedian)&(body>.15),
        "break_hold":(s*z.break8>0)&(wick>.20),
        "impulse_strong":(mom>0)&(body>.35)&(z.rangeratio>=1.15),
        "sweep_context":(s*z.sweep5>0)&(wick>0),
        "counter_reversal":(s*trend<0)&(s*z.sweep5>0)&(body>.2),
        "low_vol_continuation":(s*trend>0)&(z.atr_rank<=.5)&(mom>0),
        "high_vol_trend":(s*trend>0)&(z.atr_rank>=.5)&(z.adx14>=16),
    }
    for key,mask in controlled.items():
        g[key]=np.asarray(mask.fillna(False),bool)
    if tf=="1h":
        lon=times.tz_convert("Europe/London").hour
        ny=times.tz_convert("America/New_York").hour
        g["london_trend"]=g["trend_wide"]&((lon>=8)&(lon<16))
        g["ny_breakout"]=g["break_hold"]&((ny>=8)&(ny<13))
    if tf=="4h":
        lon=times.tz_convert("Europe/London").hour
        g["london_trend"]=g["trend_wide"]&((lon>=8)&(lon<18))
        g["london_reversal"]=g["sweep_context"]&((lon>=8)&(lon<18))
    return g


def valuation(y,mask,side,price_change,year_half,min_n):
    """Selection-year ONLY win rate, Wilson, net expectancy & support balance."""
    score=base.stats(y,mask,side)
    if score["n"]<min_n:
        return None
    signed=price_change[mask]*(1 if side=="BUY" else -1)
    mean_net=float(np.mean(signed)-base.COST_USD_OZ)
    halves=tuple(int(np.sum(mask & (year_half==k))) for k in (1,2))
    floor=int(np.ceil(min_n*CONFIG[PRESET]["min_half_share"]))
    supported=min(halves)>=floor
    out={**score,
         "val_net_usd_oz":round(mean_net,5),
         "validation_half_year_counts":list(halves),
         "validation_half_year_supported":supported}
    return out


def policy_rank(out):
    """Lexicographic precision-first selection; no test-year data."""
    if out is None:return None
    positive_net=out["val_net_usd_oz"]>0
    passes=out["accuracy"]>=.60 and out["validation_half_year_supported"]
    if not CONFIG[PRESET]["allow_neg_validation_net"]:
        # DO NOT hide losing valid setups; penalize negative net expectation.
        return (passes and positive_net,
                positive_net,out["validation_half_year_supported"],
                out["wilson_lower95"],out["coverage"])
    return (passes,out["validation_half_year_supported"],
            positive_net,out["wilson_lower95"],out["coverage"])


def fold(tf,year,d,z,y,base_valid,times,groups,gate_sets):
    annual={"year":year,"sides":{},"n_test":0,
            "coverage":0,"conflicts":0,"wait":None}
    preds={}
    ref=d.c.to_numpy(dtype=float)
    delta=d.c.shift(-1).to_numpy(dtype=float)-ref
    month=times.month
    half=np.where(month<=6,1,2)
    for side in ("BUY","SELL"):
        choices=[]
        true_label=1 if side=="BUY" else 0
        for name,group in groups.items():
            x=group.to_numpy(dtype=float)
            valid=base_valid&np.isfinite(x).all(axis=1)
            tr,va,te=base.split_masks(times,valid,year)
            min_val=CONFIG[PRESET]["minimum"][tf]
            if (tr.sum()<base.MINTRAIN[tf] or va.sum()<2*min_val
                    or te.sum()<min_val or np.unique(y[tr]).size!=2):
                continue
            g=gate_sets[side]
            known={key:np.asarray(values[va],bool) for key,values in g.items()}
            # Fail closed if OHLC-derived next-bar realized move is absent
            # from validation; this is a label, not an input feature.
            if not np.isfinite(delta[va]).all():
                continue
            for modelname in CONFIG[PRESET]["models"]:
                model=model_factory(modelname)
                model.fit(x[tr],(y[tr]==true_label).astype(np.int8))
                pv=model.predict_proba(x[va])[:,1]
                for threshold,gate in itertools.product(
                    CONFIG[PRESET]["cutoffs"],known
                ):
                    selected=(pv>=threshold)&known[gate]
                    metric=valuation(
                        y[va],selected,side,delta[va],half[va],min_val)
                    rank=policy_rank(metric)
                    if rank is None:continue
                    choices.append((rank,name,modelname,threshold,gate,
                                    model,x,te,g,metric))
        if not choices:
            annual["sides"][side]={
                "selected":None,"reason":"VALIDATION_GATES_NO_CANDIDATE"
            }
            continue
        ranked=max(choices,key=lambda t:(t[0],t[1],t[2],-t[3],t[4]))
        rank,feature,modelname,threshold,gate,model,x,te,g,validation=ranked
        probabilities=model.predict_proba(x[te])[:,1]
        triggered=(probabilities>=threshold)&np.asarray(g[gate][te],bool)
        preds[side]=(np.flatnonzero(te),np.asarray(triggered,bool))
        annual["sides"][side]={
            "selected":{
                "model":modelname,"group":feature,
                "threshold":float(threshold),"gate":gate,
                "validation":validation,"selection_rank":list(rank),
            },
            "pre_conflict":base.stats(y[te],triggered,side),
        }
    return annual,preds


def run(tf,variant):
    global PRESET
    if variant not in CONFIG:raise ValueError("R292_UNKNOWN_VARIANT")
    original=(
        base.feature_groups,base.gates,base.fold,base.MINVAL,
        base.STRATEGY,base.ENGINES,base.CUTS
    )
    PRESET=variant
    try:
        base.feature_groups=feature_groups
        base.gates=gates
        base.fold=fold
        base.MINVAL={**BASE_MIN,**CONFIG[variant]["minimum"]}
        base.CUTS=CONFIG[variant]["cutoffs"]
        base.ENGINES=CONFIG[variant]["models"]
        base.STRATEGY="R29_2_MAGNITUDE_REGIME_"+variant.upper()+"_20261123"
        result=base.run(tf)
        result["variant"]="R29.2 "+variant
        result["selection_objective"]="validation-only Wilson, half-year support and hypothetical net USD/oz"
        result["source_version"]="R29.1 + predefined liquidity/regime gates + extra trees"
        result["limitations"].append(
            "R29.2 design adapted after inspecting R29.1 results. "
            "2024-2026 fold performance is not a blind independent validation."
        )
        result["limitations"].append(
            "Validation net drift is an estimate from next candle close, "
            "not executable realized P&L. The original label remains close-to-close."
        )
        out=base.ROOT/f"r292-{variant}-{tf}.json"
        out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
        print(json.dumps({"variant":"R29.2 "+variant,"tf":base.NAME[tf],
                          "passed":result["passes_all_predeclared_gates"],
                          "coverage":result["coverage"],
                          "aggregate":result["aggregate"],
                          "receipt":str(out)}),flush=True)
        return result
    finally:
        (base.feature_groups,base.gates,base.fold,base.MINVAL,
         base.STRATEGY,base.ENGINES,base.CUTS)=original


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=("1h","4h","1D","1W"),required=True)
    p.add_argument("--variant",choices=list(CONFIG),required=True)
    q=p.parse_args()
    run(q.tf,q.variant)

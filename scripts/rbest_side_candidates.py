"""Independent research SHADOW for R25 BUY and R11 SELL on XAU H1/H4.

Uses the EXACT selected R25 2026 annual config and frozen R11 selected bit-rule
from their original GitHub archives. Every run must reproduce the historical
selection-window parity BEFORE scoring fresh, fully CLOSED cTrader broker bars.

No trading endpoints, order authority, live win-rate claims, or changes to
R28.1 / Frozen V1. Incomplete source or parity -> fail closed.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from r10_million import load as load_r10, ohlc_indicators
from r102_calibrated import prepare, context as causal_context
from r14_multitimeframe_direction import load_tf
from r25_eight_specialists import setup as r25_setup
from r11_hundred_million import anchor, rules, exactmask, bitpack
from r281_live_market import read_m1, aggregate, combine_history

ROOT = Path("research/archive/xau_r281")
ARCHIVE_R25 = {
    "1h": ROOT/"44964431677/14731141368/r25-eight-1h.json",
    "4h": ROOT/"44964431677/14730673399/r25-eight-4h.json",
}
ARCHIVE_R11 = ROOT/"44907879558/14709146843/r11-100million-summary.json"
HOURS = {"1h": 1, "4h": 4}
TFS = {"1h": "H1", "4h": "H4"}
CONTRACT = "RIZAN_BEST_SIDE_SHADOW_V1"
OUTPUT = Path("artifacts/rbest_inference")
ROWS = {"1h": ("R25", "R11"), "4h": ("R25", "R11")}


def utc(value):
    x=pd.Timestamp(value)
    if x.tzinfo is None:
        raise ValueError("RBEST_TIME_MUST_HAVE_TIMEZONE")
    return x.tz_convert("UTC")


def selected(tf):
    if tf not in TFS:
        raise ValueError("RBEST_UNSUPPORTED_TIMEFRAME")
    r25=json.loads(ARCHIVE_R25[tf].read_text())
    row=next((a for a in r25["annual"] if a["year"]==2026), None)
    if row is None or r25.get("tf") != tf:
        raise ValueError("R25_2026_POLICY_MISSING")
    conf=row["policies"]["regime_specialist"]["BUY_config"]
    if not conf or conf["model"] not in ("ridge_logit","logit","hgb"):
        raise ValueError("R25_BUY_POLICY_INVALID")
    r11=json.loads(ARCHIVE_R11.read_text())
    rule=r11["selected"][tf+"_SELL"]
    if (rule["tf"]!=tf or rule["side"]!="SELL"
            or rule["config_index"] is None or rule["family_id"] is None):
        raise ValueError("R11_SELL_POLICY_INVALID")
    return conf, rule


def freeze_r25_buy(tf, policy):
    """Refit historical 2026-fold BUY head; prove exact validation n/correct."""
    d,z,_,y,valid,times=load_tf(tf)
    groups,gates,extra=r25_setup(tf,d,z,times,None)
    valid=valid & extra
    for group in groups.values():
        valid &= np.isfinite(group.to_numpy(float)).all(axis=1)
    group=policy["group"]
    gate=policy["gate"]
    if group not in groups or gate not in gates:
        raise ValueError("R25_FEATURE_GATE_SCHEMA_MISMATCH")
    vs=pd.Timestamp("2024-01-01",tz="UTC")
    end=pd.Timestamp("2026-01-01",tz="UTC")
    matured=pd.Series(times,index=d.index).shift(-1)
    tr=valid&(times>=vs-pd.DateOffset(years=int(policy["years"])))&(matured<vs).to_numpy()
    va=valid&(times>=vs)&(times<end)&(matured<end).to_numpy()
    if tr.sum()<250 or va.sum()<70 or len(np.unique(y[tr]))!=2:
        raise ValueError("R25_TRAIN_VALIDATION_SAMPLE_MISSING")
    feat=groups[group]
    x=feat.to_numpy(float)
    kind=policy["model"]
    model=(
        HistGradientBoostingClassifier(
            max_iter=60,max_depth=2,max_leaf_nodes=5,
            l2_regularization=15,random_state=25
        ) if kind=="hgb"
        else make_pipeline(StandardScaler(),
                           LogisticRegression(C=.025 if kind=="ridge_logit" else .3,max_iter=500))
    )
    target=(y==1).astype(int)
    model.fit(x[tr],target[tr])
    active=(model.predict_proba(x[va])[:,1]>=float(policy["threshold"]))
    active &= np.asarray(gates[gate],bool)[va]
    expected=policy.get("validation") or {}
    n=int(active.sum())
    correct=int((y[va][active]==1).sum())
    if (n!=expected.get("n") or correct!=expected.get("correct")):
        raise AssertionError(f"R25_VALIDATION_PARITY_MISMATCH:{tf}:{n}/{correct}:{expected}")
    return model, {
        "parity": "PASS", "n": n, "correct": correct,
        "policy_sha256": hashlib.sha256(
            json.dumps(policy,sort_keys=True).encode()).hexdigest(),
        "feature_columns": list(feat.columns),
        "group": group, "gate": gate,
        "train_rows": int(tr.sum()),
        "training_end_exclusive": vs.isoformat(),
    }


def verify_r11_sell(tf, policy):
    """Verify original 2019–2022 training and 2023 selection trace hashes."""
    d,z,_,_,valid=prepare(tf)
    allmask=exactmask(anchor(z,"SELL",int(policy["family_id"])),
                      rules(z,"SELL"),int(policy["config_index"]))
    yrs=z.index.year
    tr=np.asarray(valid & (yrs>=2019) & (yrs<=2022))
    va=np.asarray(valid & (yrs==2023))
    if tr.sum()<1000 or va.sum()<200:
        raise ValueError("R11_ORIGINAL_SAMPLE_MISSING")
    trainhash=hashlib.sha256(bitpack(allmask[tr])).hexdigest()
    valhash=hashlib.sha256(bitpack(allmask[va])).hexdigest()
    if (trainhash!=policy.get("training_signal_sha256")
            or valhash!=policy.get("validation_signal_sha256")):
        raise AssertionError("R11_SELECTED_TRACE_PARITY_MISMATCH:"+tf)
    return {
        "parity":"PASS","historical_train_sha256":trainhash,
        "historical_validation_sha256":valhash,
        "config_sha256":hashlib.sha256(
            json.dumps(policy,sort_keys=True).encode()).hexdigest(),
    }


def live_latest(tf, now):
    """Strict M1 source freshness and full native H1/H4 bar boundary."""
    m1,meta=read_m1(now=now)
    archive=load_r10(tf)
    fresh=aggregate(m1,tf,now=now)
    combined=combine_history(archive,fresh,tf)
    if combined is None:
        raise ValueError("RBEST_BROKER_ARCHIVE_GAP_OR_PRICE_SCALE")
    historical_h1=load_r10("1h")
    latest_h1=aggregate(m1,"1h",now=now)
    merged_h1=combine_history(historical_h1,latest_h1,"1h")
    if merged_h1 is None:
        raise ValueError("RBEST_H1_BROKER_CONTEXT_UNAVAILABLE")
    latest_close=fresh.index[-1]+pd.Timedelta(hours=HOURS[tf])
    target=latest_close+pd.Timedelta(hours=HOURS[tf])
    if not (latest_close <= now < target):
        raise ValueError("RBEST_SOURCE_CANDLE_EXPIRED")
    # The history join is causal: all source candle features end at last close.
    d=combined.loc[combined.index<latest_close].copy()
    z=ohlc_indicators(d)
    causal_context(z,merged_h1,HOURS[tf])
    if d.index[-1]!=fresh.index[-1] or z.index[-1]!=d.index[-1]:
        raise ValueError("RBEST_CLOSED_SOURCE_CANDLE_MISMATCH")
    return d,z,meta,latest_close,target


def run(tf,now=None):
    now=utc(now or datetime.now(UTC))
    buycfg,sellcfg=selected(tf)
    model,buyproof=freeze_r25_buy(tf,buycfg)
    sellproof=verify_r11_sell(tf,sellcfg)
    d,z,source,closed,target=live_latest(tf,now)
    times=d.index+pd.Timedelta(hours=HOURS[tf])
    groups,gates,extra=r25_setup(tf,d,z,times,None)
    g=groups[buycfg["group"]]
    if list(g.columns)!=buyproof["feature_columns"]:
        raise ValueError("RBEST_LIVE_FEATURE_SCHEMA_MISMATCH")
    if not np.isfinite(g.iloc[-1].to_numpy(float)).all():
        raise ValueError("RBEST_LIVE_FEATURE_VALUES_MISSING")
    p=float(model.predict_proba(g.iloc[-1:].to_numpy(float))[0,1])
    gate=bool(np.asarray(gates[buycfg["gate"]],bool)[-1])
    buy=bool(p>=float(buycfg["threshold"]) and gate)
    anchors=anchor(z,"SELL",int(sellcfg["family_id"]))
    masks=rules(z,"SELL")
    sell=bool(exactmask(anchors,masks,int(sellcfg["config_index"]))[-1])
    direction="WAIT" if buy==sell else ("BUY" if buy else "SELL")
    reason=("SIDE_CONFLICT" if buy and sell else "NO_SIDE_TRIGGER" if not buy and not sell
            else "RESEARCH_CANDIDATE_SIGNAL")
    # Broker transport is read AFTER run-start 'now'. Its observed_at may be
    # milliseconds later than run-start; publishing the earlier start time
    # violates the causal ordering contract (observed <= generated).
    # Preserve both timestamps without relaxing freshness/expiry checks.
    observed=utc(source["as_of"])
    generated=max(now,observed)
    result={
        "contract": CONTRACT, "tf":TFS[tf], "research_only":True,
        "source":"CTRADER_MARKET_DATA_READ_ONLY",
        "execution_authority":False,"execution_influence":False,
        "generated_at":generated.isoformat(),"observed_at":observed.isoformat(),
        "candle_closed_at":closed.isoformat(),
        "target_close_at":target.isoformat(),
        "last_close":float(d.c.iloc[-1]),
        "direction":direction,"reason":reason,
        "sides":{
            "BUY":{"version":"R25","active":buy,"score":p,
                   "threshold":float(buycfg["threshold"]),
                   "gate":buycfg["gate"],"gate_pass":gate,
                   "parity":buyproof},
            "SELL":{"version":"R11","active":sell,"score":None,
                    "threshold":None,"parity":sellproof},
        },
        "limitations":[
            "R25 2026 selected head was evaluated on previously inspected historical folds",
            "R11 historical selected 2023 rule had negative estimated net PnL",
            "Not forward validated or broker-vendor price-feature parity proven",
            "A conflict or lack of side activation is WAIT, not zero-probability",
            "No trade entry, margin, stop, target or brokerage execution authority",
        ],
    }
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/f"rbest-{tf}-shadow.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("limitations","sides")},
                     allow_nan=False),flush=True)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--tf",choices=list(TFS),required=True)
    args=p.parse_args()
    run(args.tf)

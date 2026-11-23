"""R29.4 frozen 2026-fold R29.2 H4 BUY, broker-only read-only SHADOW.

The 62.70% R29.2 figure pools 2024/2025/2026 DIFFERENT policies.
Only the 2026 policy is allowed here: ridge / broad_context / 0.54 /
trend_impulse, fitted on 2019–2024 and validated on 2025 (63/41).
2026 replay 14/23 is historical, previously inspected, NOT live assurance.

A fresh, fully CLOSED cTrader H4 candle can yield BUY_SHADOW or WAIT_MODEL.
No SELL is invented and no original R28.1 / R25 / Frozen V1 engine is changed.
"""
from __future__ import annotations
import hashlib
import json
from datetime import UTC,datetime
from pathlib import Path

import numpy as np
import pandas as pd

from r14_multitimeframe_direction import load_tf
from r10_million import load as load_r10,ohlc_indicators
from r102_calibrated import context as causal_context
from r281_live_market import read_m1,aggregate,combine_history
import r292_magnitude_regime_expansion as r292
import r29_direction60_walkforward as base

TF="4h"
CONTRACT="RIZAN_R294_FROZEN_R292_H4_BUY_SHADOW_V1"
MODEL_ID="R29_2_H4_BUY_PRECISION_2026_FOLD_FROZEN_20261123"
SOURCE="CTRADER_MARKET_DATA_READ_ONLY"
LOCK=Path("research/RIZAN_R292_H4_BUY_PRECISION_RESEARCH_LOCK_20261123.json")
OUTPUT=Path("runtime/r294-h4-buy-shadow.json")
POLICY={"model":"ridge","group":"broad_context",
        "threshold":0.54,"gate":"trend_impulse"}
EVAL2026={"n":23,"correct":14}
VAL2025={"n":63,"correct":41}
POOLED={"n":126,"correct":79}
ARTIFACT_SHA="f5fb876d38b5e8e8599037d1474aa6c2c62ffc3a8ba3a66c845916a8bc2aaa2c"
HOURS=4


def utc(value):
    p=pd.Timestamp(value)
    if p.tzinfo is None:raise ValueError("R294_TIMESTAMP_NOT_UTC")
    return p.tz_convert("UTC")


def verify_lock():
    lock=json.loads(LOCK.read_text())
    if (lock.get("id")!="RIZAN_R292_H4_BUY_PRECISION_RESEARCH_CANDIDATE_20261123"
            or lock.get("symbol")!="XAUUSD" or lock.get("side")!="BUY"
            or lock.get("timeframe")!="H4"
            or lock.get("source_json_sha256")!=ARTIFACT_SHA
            or lock.get("execution_authority") is not False
            or lock.get("execution_influence") is not False):
        raise ValueError("R294_FROZEN_LOCK_PROVENANCE_MISMATCH")
    row=next((a for a in lock["folds"] if a["evaluation_year"]==2026),None)
    # The historical lock calls this field feature_group; the runtime
    # sklearn matrix argument is named group. Compare values, not labels.
    locked_policy = ({
        "model":row.get("model"),
        "group":row.get("feature_group"),
        "threshold":row.get("threshold"),
        "gate":row.get("gate"),
    } if row is not None else {})
    if (row is None or locked_policy!=POLICY
            or row.get("validation_year")!=2025
            or any(int(row["validation"][key])!=VAL2025[label]
                   for key,label in (("n","n"),("correct","correct")))
            or any(int(row["evaluation"][key])!=EVAL2026[key]
                   for key in ("n","correct"))
            or any(int(lock["aggregate"][key])!=POOLED[key]
                   for key in ("n","correct"))):
        raise ValueError("R294_FROZEN_2026_FOLD_POLICY_MISMATCH")
    return lock


def verified_refit():
    """No 2025/2026 outcomes used for the training target or model choice."""
    lock=verify_lock()
    d,z,_,y,valid,times=load_tf(TF)
    groups=r292.feature_groups(TF,d,z)
    X=groups[POLICY["group"]].to_numpy(float)
    gate=r292.gates(TF,z,times,"BUY")[POLICY["gate"]]
    valid=valid&np.isfinite(X).all(axis=1)
    tr,va,te=base.split_masks(times,valid,2026,window=6)
    if not (tr.sum()>500 and va.sum()>500 and te.sum()>500):
        raise ValueError("R294_TRAINING_OR_VALIDATION_CANDLES_MISSING")
    if (times[tr].max()>=pd.Timestamp("2025-01-01",tz="UTC")
            or times[va].min()<pd.Timestamp("2025-01-01",tz="UTC")):
        raise ValueError("R294_TRAINING_LOOKAHEAD")
    mdl=r292.model_factory(POLICY["model"])
    mdl.fit(X[tr],(y[tr]==1).astype("int8"))
    p=mdl.predict_proba(X[va])[:,1]
    fired=(p>=POLICY["threshold"]) & np.asarray(gate[va],bool)
    n=int(fired.sum());correct=int((y[va][fired]==1).sum())
    if (n,correct)!=(VAL2025["n"],VAL2025["correct"]):
        raise AssertionError(f"R294_2025_PARITY_MISMATCH:{n}/{correct}")
    return mdl,{
        "status":"PASS", "selection_year":2025,
        "training_end_exclusive":"2025-01-01T00:00:00+00:00",
        "selected_policy":POLICY, "validation":{"n":n,"correct":correct},
        "feature_columns":list(groups[POLICY["group"]].columns),
        "train_bars":int(tr.sum()),
        "lock_sha256":hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        "evidence_sha256":ARTIFACT_SHA,
    }


def broker_latest(*,now):
    """Fresh broker M1 + immutable R10 archive, with strict 4h candle close."""
    now=utc(now)
    bars,meta=read_m1(now=now)
    native=aggregate(bars,TF,now=now)
    if native.empty:raise ValueError("R294_NO_FULL_CLOSED_BROKER_H4")
    d=combine_history(load_r10(TF),native,TF)
    if d is None:raise ValueError("R294_H4_ARCHIVE_BROKER_GAP")
    one=aggregate(bars,"1h",now=now)
    h1=combine_history(load_r10("1h"),one,"1h")
    if h1 is None:raise ValueError("R294_H1_CONTEXT_ARCHIVE_BROKER_GAP")
    closed=native.index[-1]+pd.Timedelta(hours=HOURS)
    target=closed+pd.Timedelta(hours=HOURS)
    if not (closed<=now<target):
        raise ValueError("R294_SOURCE_BAR_STALE_OR_UNCLOSED")
    d=d.loc[d.index<closed]
    z=ohlc_indicators(d)
    causal_context(z,h1,HOURS)
    if d.index[-1]!=native.index[-1]:
        raise ValueError("R294_BROKER_CANDLE_BOUNDARY_MISMATCH")
    return d,z,meta,closed,target


def run(*,now=None):
    now=utc(now or datetime.now(UTC))
    if now.year!=2026:
        raise ValueError("R294_2026_POLICY_HAS_NOT_BEEN_REVALIDATED_FOR_NEW_YEAR")
    model,proof=verified_refit()
    d,z,source,closed,target=broker_latest(now=now)
    times=d.index+pd.Timedelta(hours=HOURS)
    groups=r292.feature_groups(TF,d,z)
    matrix=groups[POLICY["group"]]
    if list(matrix.columns)!=proof["feature_columns"]:
        raise ValueError("R294_FEATURE_SCHEMA_DIFFERENT_FROM_FROZEN_REFIT")
    last=matrix.iloc[-1:].to_numpy(float)
    if not np.isfinite(last).all():
        raise ValueError("R294_CURRENT_FEATURE_NOT_FINITE")
    probability=float(model.predict_proba(last)[0,1])
    gate=bool(np.asarray(
        r292.gates(TF,z,times,"BUY")[POLICY["gate"]],bool)[-1])
    triggered=bool(probability>=POLICY["threshold"] and gate)
    packet={
        "contract":CONTRACT,"model_id":MODEL_ID,"symbol":"XAUUSD",
        "tf":"H4","side":"BUY","source":SOURCE,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forward_validated":False,
        "generated_at":now.isoformat(),"observed_at":source["as_of"],
        "candle_closed_at":closed.isoformat(),
        "target_close_at":target.isoformat(),
        "latest_broker_close":float(d.c.iloc[-1]),
        "direction":"BUY" if triggered else "WAIT",
        "reason":"H4_BUY_FROZEN_R292_TRIGGER" if triggered else "BELOW_THRESHOLD_OR_GATE",
        "buy_head":{"model":POLICY["model"],"feature_group":POLICY["group"],
                    "threshold":POLICY["threshold"],"gate":POLICY["gate"],
                    "probability":probability,"gate_pass":gate,
                    "triggered":triggered},
        "provenance":proof,
        "historical_pooled":{"correct":79,"n":126,"accuracy":0.626984},
        "historical_2026_policy":{"correct":14,"n":23,"accuracy":0.608696},
        "limitations":[
            "62.70pct pools different 2024/2025/2026 selected policies",
            "2026 frozen model itself was retrospectively 14/23, not validated live",
            "Neither direction probability nor expected forward profitability is guaranteed",
            "A frozen H4 BUY trigger does not authorize entry without independent SMC risk checks",
            "No SELL policy has been approved by R29.2",
        ],
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(packet,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"tf":"H4","direction":packet["direction"],
                      "reason":packet["reason"],"score":probability,
                      "gate_pass":gate,"target":target.isoformat(),
                      "provenance":proof["status"]}),flush=True)
    return packet


if __name__=="__main__":
    run()

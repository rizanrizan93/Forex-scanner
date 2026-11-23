"""R29.6 freeze two ORIGINAL R29.1 H4 BUY heads on closed broker H4.

2025 high-coverage champion is an EXPERIMENTAL 2026 carry-forward; it was
selected on 2024 validation, NOT selected again on 2026 test outcomes.
Original 2026-selected 13-signal model is included for historical parity.
Original 59.94% is pooled over distinct yearly policies, NEVER live confidence.
No SELL or orders. Does not replace R29.2 / Frozen V1 / R28.1.
"""
from __future__ import annotations
import hashlib,json
from datetime import UTC,datetime
from pathlib import Path
import numpy as np
import pandas as pd

import r29_direction60_walkforward as baseline
import r291_event_structure_direction as r291
import r294_frozen_h4_buy_shadow as broker

LOCK=Path("research/RIZAN_R291_H4_BUY_COVERAGE_FROZEN_20261123.json")
OUTPUT=Path("runtime/r296-h4-buy-coverage-shadow.json")
CONTRACT="RIZAN_R296_R291_H4_BUY_COVERAGE_SHADOW_V1"
MODEL_ID="R29_1_H4_BUY_TWO_YEAR_POLICY_FROZEN_20261123"
SOURCE="CTRADER_MARKET_DATA_READ_ONLY"
SOURCE_SHA="943e82b27b27c519774e7046aa313391633bdfb42ea17e6c187059e3931ad1fc"
EXPECTED={
    "2025":{"validation":{"n":174,"correct":109},"evaluation":{"n":176,"correct":108}},
    "2026":{"validation":{"n":48,"correct":32},"evaluation":{"n":13,"correct":8}},
}
LANES={"2025":"HIGH_COVERAGE_2025_CARRY","2026":"ORIGINAL_2026_SELECTION"}


def utc(x):
    t=pd.Timestamp(x)
    if t.tzinfo is None:raise ValueError("R296_NAIVE_TIMESTAMP")
    return t.tz_convert("UTC")


def locked():
    x=json.loads(LOCK.read_text())
    if (x.get("id")!="RIZAN_R291_H4_BUY_HIGH_COVERAGE_HISTORICAL_FROZEN_20261123"
            or x.get("source_json_sha256")!=SOURCE_SHA
            or x.get("historical_pooled",{}).get("n")!=332
            or x.get("historical_pooled",{}).get("correct")!=199
            or x.get("execution_authority") is not False
            or x.get("execution_influence") is not False
            or x.get("forward_validated") is not False):
        raise ValueError("R296_FROZEN_LOCK_INVALID")
    for yr in LANES:
        row=x["annual_policies"][yr]
        if (row["selection_validation"]["n"],row["selection_validation"]["correct"])!=(
                EXPECTED[yr]["validation"]["n"],EXPECTED[yr]["validation"]["correct"]):
            raise ValueError("R296_ORIGINAL_SELECTION_MISMATCH_"+yr)
        if (row["evaluation"]["n"],row["evaluation"]["correct"])!=(
                EXPECTED[yr]["evaluation"]["n"],EXPECTED[yr]["evaluation"]["correct"]):
            raise ValueError("R296_ORIGINAL_EVALUATION_MISMATCH_"+yr)
    return x


def train_historical(policy_year):
    """Fit only prior-year train label-matured source and prove selection parity."""
    lock=locked()
    year=int(policy_year)
    d,z,_,y,valid,times=baseline.load_tf("4h")
    groups=r291.feature_groups("4h",d,z)
    gates=r291.gates("4h",z,times,"BUY")
    p=lock["annual_policies"][policy_year]["policy"]
    if p["group"] not in groups or p["gate"] not in gates:
        raise ValueError("R296_ORIGINAL_FEATURE_OR_GATE_UNKNOWN")
    x=groups[p["group"]].to_numpy(dtype=float)
    valid=valid & np.isfinite(x).all(axis=1)
    tr,va,te=baseline.split_masks(times,valid,year,window=6)
    if min(tr.sum(),va.sum(),te.sum())<100:
        raise ValueError("R296_TRAIN_VALIDATION_OR_EVALUATION_SHORT")
    start=pd.Timestamp(f"{year-1}-01-01",tz="UTC")
    if (times[tr].max()>=start or times[va].min()<start
            or times[va].max()>=pd.Timestamp(f"{year}-01-01",tz="UTC")):
        raise ValueError("R296_RESEARCH_LABEL_LOOKAHEAD")
    m=baseline.model_factory(p["model"])
    m.fit(x[tr],(y[tr]==1).astype(np.int8))
    probs=m.predict_proba(x[va])[:,1]
    fired=(probs>=p["threshold"]) & np.asarray(gates[p["gate"]],bool)[va]
    nk={"n":int(fired.sum()),"correct":int(np.sum(y[va][fired]==1))}
    if nk!=EXPECTED[policy_year]["validation"]:
        raise AssertionError(f"R296_ORIGINAL_VAL_PARITY_FAIL:{policy_year}:{nk}")
    # Score original evaluation for SOURCE parity only; not used to fit/retune.
    q=m.predict_proba(x[te])[:,1]
    active=(q>=p["threshold"]) & np.asarray(gates[p["gate"]],bool)[te]
    evalproof={"n":int(active.sum()),"correct":int(np.sum(y[te][active]==1))}
    if evalproof!=EXPECTED[policy_year]["evaluation"]:
        raise AssertionError(f"R296_ORIGINAL_EVAL_PARITY_FAIL:{policy_year}:{evalproof}")
    # Out-of-policy carry-forward diagnostic, not a pristine test.
    te26=baseline.split_masks(times,valid,2026)[2]
    carry=m.predict_proba(x[te26])[:,1]
    trigger=(carry>=p["threshold"]) & np.asarray(gates[p["gate"]],bool)[te26]
    backtest=baseline.stats(y[te26],trigger,"BUY",base={
        "reference_close":d.c.to_numpy(float)[te26],
        "next_close":d.c.shift(-1).to_numpy(float)[te26],
        "next_high":d.h.shift(-1).to_numpy(float)[te26],
        "next_low":d.l.shift(-1).to_numpy(float)[te26]})
    proof={
        "status":"PASS","year_policy":year,"selected_on_validation_year":year-1,
        "training_end_exclusive":start.isoformat(),
        "source_json_sha256":SOURCE_SHA,
        "lock_sha256":hashlib.sha256(LOCK.read_bytes()).hexdigest(),
        "feature_columns":list(groups[p["group"]].columns),
        "policy":p,"validation":nk,"original_evaluation":evalproof,
        "carry_2026_diagnostic":backtest,
        "train_rows":int(tr.sum())
    }
    return m,proof


def run(*,now=None):
    now=utc(now or datetime.now(UTC))
    if now.year!=2026:
        raise ValueError("R296_CURRENT_POLICY_EXPIRED_IN_2027")
    models={yr:train_historical(yr) for yr in LANES}
    d,z,source,closed,target=broker.broker_latest(now=now)
    livegroups=r291.feature_groups("4h",d,z)
    gates=r291.gates("4h",z,d.index+pd.Timedelta(hours=4),"BUY")
    lanes={}
    for yr,name in LANES.items():
        m,proof=models[yr]
        p=proof["policy"]
        x=livegroups[p["group"]]
        if list(x.columns)!=proof["feature_columns"] or not np.isfinite(x.iloc[-1].to_numpy(float)).all():
            raise ValueError("R296_LIVE_BROKER_FEATURE_PARITY_FAIL_"+yr)
        score=float(m.predict_proba(x.iloc[-1:].to_numpy(float))[0,1])
        gate=bool(np.asarray(gates[p["gate"]],bool)[-1])
        triggered=bool(score>=p["threshold"] and gate)
        lanes[name]={
            "policy_year":int(yr),"direction":"BUY" if triggered else "WAIT",
            "reason":"FROZEN_H4_BUY_TRIGGER" if triggered else "FROZEN_GATE_OR_SCORE_NOT_MET",
            "score":score,"gate_pass":gate,"triggered":triggered,
            "policy":p,"proof":proof,
        }
    packet={
        "contract":CONTRACT,"model_id":MODEL_ID,"symbol":"XAUUSD","tf":"H4",
        "source":SOURCE,"side":"BUY","research_only":True,
        "execution_authority":False,"execution_influence":False,
        "forward_validated":False,"generated_at":now.isoformat(),
        "observed_at":source["as_of"],"candle_closed_at":closed.isoformat(),
        "target_close_at":target.isoformat(),"last_close":float(d.c.iloc[-1]),
        "historical_pooled":{"n":332,"correct":199,"accuracy":199/332},
        "lanes":lanes,
        "limitations":[
            "Historical 332 signals are pooled across 3 different yearly policies",
            "2025 carry model is extrapolated beyond its originally selected evaluation year",
            "2026 selected model had 13 BUY signals and negative 2026 after-cost expectancy",
            "No independent fresh forward trial supports any 59.94% live win-rate",
            "Do not conflate simultaneous BUY candidate triggers with order authorization"
        ]
    }
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(packet,indent=2,allow_nan=False)+"\n")
    print(json.dumps({
        "as_of":packet["generated_at"],"source":packet["source"],
        "target":packet["target_close_at"],
        "lanes":{k:{"direction":v["direction"],"score":v["score"],
                  "gate_pass":v["gate_pass"],
                  "validation":v["proof"]["validation"],
                  "carry_2026":v["proof"]["carry_2026_diagnostic"]}
                 for k,v in lanes.items()}
    }),flush=True)
    return packet


if __name__=="__main__":run()

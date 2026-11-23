"""R29.6 fail-closed two-lane H4 BUY research publisher, never orders."""
from datetime import UTC,datetime
import json,math
from pathlib import Path
import pandas as pd
import r296_h4_coverage_live_shadow as core

CONTRACT=core.CONTRACT
POLICIES={
 "HIGH_COVERAGE_2025_CARRY":{"model":"hgb","group":"event_bos_context",
                             "threshold":.50,"gate":"trend_impulse"},
 "ORIGINAL_2026_SELECTION":{"model":"ridge","group":"event_geometry",
                            "threshold":.53,"gate":"bos_displacement"}
}
VAL={"HIGH_COVERAGE_2025_CARRY":{"n":174,"correct":109},
     "ORIGINAL_2026_SELECTION":{"n":48,"correct":32}}
EVAL={"HIGH_COVERAGE_2025_CARRY":{"n":176,"correct":108},
      "ORIGINAL_2026_SELECTION":{"n":13,"correct":8}}

def utc(x):
    t=pd.Timestamp(x)
    if t.tzinfo is None:raise ValueError("R296_PUBLISH_NAIVE_TIMESTAMP")
    return t.tz_convert("UTC")

def validate(doc,*,now):
    now=utc(now)
    if (doc.get("contract")!=CONTRACT or doc.get("model_id")!=core.MODEL_ID
            or doc.get("symbol")!="XAUUSD" or doc.get("tf")!="H4"
            or doc.get("side")!="BUY" or doc.get("source")!=core.SOURCE
            or doc.get("research_only") is not True
            or doc.get("execution_authority") is not False
            or doc.get("execution_influence") is not False
            or doc.get("forward_validated") is not False):
        raise ValueError("R296_PUBLISH_CONTRACT_MISMATCH")
    if (doc.get("historical_pooled") or {}).get("n")!=332 or (
        doc.get("historical_pooled") or {}).get("correct")!=199:
        raise ValueError("R296_PUBLISH_POOLED_FORGED")
    if set(doc.get("lanes",{}))!=set(POLICIES):
        raise ValueError("R296_PUBLISH_LANES_MISSING")
    published=utc(doc["generated_at"])
    observed=utc(doc["observed_at"])
    closed=utc(doc["candle_closed_at"])
    target=utc(doc["target_close_at"])
    if (target-closed!=pd.Timedelta(hours=4)
            or not closed<=observed<=published<=now
            or (published-observed).total_seconds()>300
            or not 0<=(now-published).total_seconds()<=1200
            or now>=target or now.year!=2026):
        raise ValueError("R296_PUBLISH_CANDLE_STALE")
    for lane,expected_policy in POLICIES.items():
        row=doc["lanes"][lane]
        proof=row.get("proof") or {}
        if (row.get("policy")!=expected_policy
                or proof.get("status")!="PASS"
                or proof.get("policy")!=expected_policy
                or proof.get("source_json_sha256")!=core.SOURCE_SHA
                or proof.get("validation")!=VAL[lane]
                or proof.get("original_evaluation")!=EVAL[lane]
                or (not isinstance(proof.get("feature_columns"),list))
                or len(proof["feature_columns"])<15
                or proof.get("year_policy")!=(2025 if lane=="HIGH_COVERAGE_2025_CARRY" else 2026)):
            raise ValueError("R296_PUBLISH_FROZEN_PROOF_MISMATCH_"+lane)
        score=row.get("score")
        gate=row.get("gate_pass")
        triggered=row.get("triggered")
        if (type(score) not in (int,float) or not math.isfinite(score)
                or not 0<=score<=1 or type(gate) is not bool
                or type(triggered) is not bool):
            raise ValueError("R296_PUBLISH_HEAD_INVALID_"+lane)
        expected=bool(score>=expected_policy["threshold"] and gate)
        if (triggered!=expected
                or row.get("direction")!=("BUY" if expected else "WAIT")
                or row.get("reason")!=("FROZEN_H4_BUY_TRIGGER" if expected
                                      else "FROZEN_GATE_OR_SCORE_NOT_MET")):
            raise ValueError("R296_PUBLISH_FORGED_DIRECTION_"+lane)
    return doc

if __name__=="__main__":
    packet=json.loads(Path(core.OUTPUT).read_text())
    validate(packet,now=datetime.now(UTC))
    print(json.dumps({"status":"VALID_FROZEN_H4_BUY_COVERAGE_SHADOW",
        "lanes":{k:v["direction"] for k,v in packet["lanes"].items()},
        "target":packet["target_close_at"]}),flush=True)

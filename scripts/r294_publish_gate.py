"""Fail-closed R29.4 H4 BUY SHADOW publication gate; no model fitting."""
from datetime import UTC,datetime
import json
import math
from pathlib import Path
import pandas as pd

import r294_frozen_h4_buy_shadow as model

SOURCE=model.SOURCE
CONTRACT=model.CONTRACT


def utc(v):
    p=pd.Timestamp(v)
    if p.tzinfo is None:raise ValueError("R294_PUBLISH_TIMESTAMP_NAIVE")
    return p.tz_convert("UTC")


def validate(payload,*,now):
    now=utc(now)
    if (payload.get("contract")!=CONTRACT
            or payload.get("model_id")!=model.MODEL_ID
            or payload.get("source")!=SOURCE
            or payload.get("symbol")!="XAUUSD"
            or payload.get("tf")!="H4"
            or payload.get("side")!="BUY"
            or payload.get("research_only") is not True
            or payload.get("execution_authority") is not False
            or payload.get("execution_influence") is not False
            or payload.get("forward_validated") is not False):
        raise ValueError("R294_PUBLISH_CONTRACT_MISMATCH")
    q=payload.get("provenance") or {}
    if (q.get("status")!="PASS"
            or q.get("selected_policy")!=model.POLICY
            or q.get("validation")!=model.VAL2025
            or q.get("training_end_exclusive")!="2025-01-01T00:00:00+00:00"
            or q.get("evidence_sha256")!=model.ARTIFACT_SHA
            or not isinstance(q.get("feature_columns"),list)
            or len(q["feature_columns"])<15):
        raise ValueError("R294_PUBLISH_PROVENANCE_INVALID")
    issued=utc(payload["generated_at"])
    seen=utc(payload["observed_at"])
    closed=utc(payload["candle_closed_at"])
    target=utc(payload["target_close_at"])
    if (not 0<=(now-issued).total_seconds()<=1200
            or not closed<=seen<=issued<=now
            or (issued-seen).total_seconds()>300
            or target-closed!=pd.Timedelta(hours=4)
            or now>=target or now.year!=2026):
        raise ValueError("R294_PUBLISH_STALE_OR_UNCLOSED")
    head=payload.get("buy_head") or {}
    p=head.get("probability")
    gate=head.get("gate_pass")
    active=head.get("triggered")
    if (head.get("model")!=model.POLICY["model"]
            or head.get("feature_group")!=model.POLICY["group"]
            or head.get("gate")!=model.POLICY["gate"]
            or head.get("threshold")!=model.POLICY["threshold"]
            or type(p) not in (float,int) or not math.isfinite(p) or not 0<=p<=1
            or type(gate) is not bool or type(active) is not bool):
        raise ValueError("R294_PUBLISH_FROZEN_SCORE_INVALID")
    expected=p>=model.POLICY["threshold"] and gate
    if (active!=expected
            or payload.get("direction")!=("BUY" if expected else "WAIT")
            or payload.get("reason")!=(
                "H4_BUY_FROZEN_R292_TRIGGER" if expected else "BELOW_THRESHOLD_OR_GATE")):
        raise ValueError("R294_PUBLISH_SIGNAL_INCONSISTENT")
    p2026=payload.get("historical_2026_policy") or {}
    pooled=payload.get("historical_pooled") or {}
    if ((p2026.get("n"),p2026.get("correct"))!=(23,14)
            or (pooled.get("n"),pooled.get("correct"))!=(126,79)):
        raise ValueError("R294_PUBLISH_BENCHMARK_FORGED")
    return payload


if __name__=="__main__":
    packet=json.loads(Path(model.OUTPUT).read_text())
    validate(packet,now=datetime.now(UTC))
    print(json.dumps({"contract":CONTRACT,"status":"VALID_CTRADER_READ_ONLY_SHADOW",
                      "direction":packet["direction"],
                      "expires":packet["target_close_at"]}),flush=True)

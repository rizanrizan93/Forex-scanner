"""Validated, read-only R29.2 frozen H4 BUY SHADOW transport for ForexScanner.

The historical 62.70% is pooled across DIFFERENT annual policies; only the
2026-selected 14/23 model is scored live, with 2025 41/63 parity.
No execution authority, no SELL signal, no replacement of R28/R25/cBots.
"""
from __future__ import annotations
from datetime import UTC,datetime
import base64
import binascii
import json
import math
from urllib.request import Request,urlopen

import pandas as pd

CONTRACT="RIZAN_R294_FROZEN_R292_H4_BUY_SHADOW_V1"
MODEL_ID="R29_2_H4_BUY_PRECISION_2026_FOLD_FROZEN_20261123"
SOURCE="CTRADER_MARKET_DATA_READ_ONLY"
POLICY={"model":"ridge","group":"broad_context",
        "threshold":.54,"gate":"trend_impulse"}
ARTIFACT_SHA="f5fb876d38b5e8e8599037d1474aa6c2c62ffc3a8ba3a66c845916a8bc2aaa2c"
RAW=("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
     "research/r294-frozen-h4-buy-shadow-20261123/runtime/r294-h4-buy-shadow.json")
API=("https://api.github.com/repos/rizanrizan93/Forex-scanner/contents/"
     "runtime/r294-h4-buy-shadow.json"
     "?ref=research%2Fr294-frozen-h4-buy-shadow-20261123")


def utc(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None:raise ValueError("R294_DASHBOARD_TIMESTAMP_NAIVE")
    return t.tz_convert("UTC")


def blank(reason,*,expired_at=None,issued=None):
    return {
        "direction":"WAIT","state":"WAIT_DATA","reason":reason,
        "score":None,"threshold":.54,"gate_pass":None,"closed":None,
        "target":None,"observed":None,"issued":issued,
        "expired_at":expired_at,"execution_authority":False,
        "pooled_historical_accuracy":.626984,
        "frozen_2026_historical_accuracy":.608696,
    }


def validate(payload,*,now):
    now=utc(now)
    if (not isinstance(payload,dict)
            or payload.get("contract")!=CONTRACT
            or payload.get("model_id")!=MODEL_ID
            or payload.get("source")!=SOURCE
            or payload.get("symbol")!="XAUUSD"
            or payload.get("tf")!="H4"
            or payload.get("side")!="BUY"
            or payload.get("research_only") is not True
            or payload.get("execution_authority") is not False
            or payload.get("execution_influence") is not False
            or payload.get("forward_validated") is not False):
        raise ValueError("R294_DASHBOARD_MODEL_CONTRACT_INVALID")
    proof=payload.get("provenance") or {}
    if (proof.get("status")!="PASS"
            or proof.get("selected_policy")!=POLICY
            or proof.get("validation")!={"n":63,"correct":41}
            or proof.get("training_end_exclusive")!="2025-01-01T00:00:00+00:00"
            or proof.get("evidence_sha256")!=ARTIFACT_SHA
            or not isinstance(proof.get("feature_columns"),list)
            or len(proof["feature_columns"])<15):
        raise ValueError("R294_DASHBOARD_FROZEN_2026_MODEL_PROOF_INVALID")
    if (payload.get("historical_pooled") or {}).get("n")!=126 or (
        payload.get("historical_pooled") or {}).get("correct")!=79 or (
        payload.get("historical_2026_policy") or {}).get("n")!=23 or (
        payload.get("historical_2026_policy") or {}).get("correct")!=14:
        raise ValueError("R294_DASHBOARD_HISTORICAL_BENCHMARK_MISMATCH")
    issued=utc(payload["generated_at"])
    observed=utc(payload["observed_at"])
    closed=utc(payload["candle_closed_at"])
    target=utc(payload["target_close_at"])
    if (target-closed!=pd.Timedelta(hours=4)
            or not closed<=observed<=issued
            or (issued-observed).total_seconds()>300
            or not (0<=(now-issued).total_seconds()<=7*86400)
            or issued.year!=2026):
        raise ValueError("R294_DASHBOARD_PRICE_OR_TIME_INVALID")
    head=payload.get("buy_head") or {}
    score=head.get("probability")
    gate=head.get("gate_pass")
    trigger=head.get("triggered")
    if (head.get("model")!="ridge"
            or head.get("feature_group")!="broad_context"
            or head.get("gate")!="trend_impulse"
            or head.get("threshold")!=.54
            or type(score) not in (float,int)
            or not math.isfinite(score) or not 0<=score<=1
            or type(gate) is not bool
            or type(trigger) is not bool):
        raise ValueError("R294_DASHBOARD_FROZEN_HEAD_INVALID")
    expected=bool(score>=.54 and gate)
    if (trigger!=expected
            or payload.get("direction")!=("BUY" if expected else "WAIT")
            or payload.get("reason")!=(
                "H4_BUY_FROZEN_R292_TRIGGER" if expected else "BELOW_THRESHOLD_OR_GATE")):
        raise ValueError("R294_DASHBOARD_SIGNAL_INCONSISTENT")
    if now>=target:
        return blank("TARGET_CANDLE_EXPIRED",expired_at=target.isoformat(),
                     issued=issued.isoformat())
    return {
        "direction":"BUY" if expected else "WAIT",
        "state":"RESEARCH_SHADOW" if expected else "MODEL_ABSTAIN",
        "reason":payload["reason"],
        "score":float(score),"threshold":.54,"gate_pass":gate,
        "closed":closed.isoformat(),"target":target.isoformat(),
        "observed":observed.isoformat(),"issued":issued.isoformat(),
        "expired_at":None,"execution_authority":False,
        "pooled_historical_accuracy":.626984,
        "frozen_2026_historical_accuracy":.608696,
    }


def _fetch(request,opener,*,api=False):
    with opener(request,timeout=6) as stream:
        body=stream.read(250_001)
    if len(body)>250_000:raise ValueError("R294_FEED_TOO_LARGE")
    packet=json.loads(body)
    if api:
        if (not isinstance(packet,dict) or packet.get("encoding")!="base64"
                or not isinstance(packet.get("content"),str)):
            raise ValueError("R294_GITHUB_API_RESPONSE_INVALID")
        try:body=base64.b64decode(packet["content"],validate=False)
        except (binascii.Error,ValueError) as exc:
            raise ValueError("R294_GITHUB_B64_INVALID") from exc
        packet=json.loads(body)
    return packet


def fetch(*,now=None,opener=urlopen):
    now=utc(now or datetime.now(UTC))
    h={"User-Agent":"RIZAN-R294-frozen-H4-buy-shadow/1",
       "Cache-Control":"no-cache"}
    request=Request(RAW+"?slot="+str(int(now.timestamp()//30)),headers=h)
    try:
        return validate(_fetch(request,opener),now=now)
    except (OSError,TimeoutError,ValueError,KeyError,TypeError):
        request=Request(API,headers={**h,"Accept":"application/vnd.github+json"})
        return validate(_fetch(request,opener,api=True),now=now)

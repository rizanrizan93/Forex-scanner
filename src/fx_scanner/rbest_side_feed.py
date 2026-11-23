"""Read-only reconstruction of R25 BUY and R11 SELL specialists, never orders.

Each live candidate is admitted only with original selection parity, fresh
broker candle, correct horizon and research-only source contract. Historical
leaderboard percentages cannot become forecasts without the validated packet.
"""
from __future__ import annotations

from datetime import UTC, datetime
import base64
import binascii
import json
import math
from urllib.request import Request,urlopen

import pandas as pd

CONTRACT="RIZAN_BEST_SIDE_SHADOW_SNAPSHOT_V1"
SOURCE="CTRADER_MARKET_DATA_READ_ONLY"
RAW=("https://raw.githubusercontent.com/rizanrizan93/Forex-scanner/"
     "research/rbest-side-inference-20261123/runtime/rbest-side-direction.json")
API=("https://api.github.com/repos/rizanrizan93/Forex-scanner/contents/"
     "runtime/rbest-side-direction.json"
     "?ref=research%2Frbest-side-inference-20261123")
CANDIDATES={
    "H1":{"BUY":"R25","SELL":"R11"},
    "H4":{"BUY":"R25","SELL":"R11"},
    "D1":{"BUY":"R28.1","SELL":"R18"},
    "W1":{"BUY":"R27","SELL":"R24"},
}
KNOWN_R25_VALIDATION={"H1":(325,204),"H4":(72,51)}
KNOWN_R11_TRAIN_HASH={
    "H1":"5189b65a8bbefeb0380f5795ca3639ac663debf337e625eadd4f552289aa044d",
    "H4":"a172c3a659224862db0d3bde24642ed56b5c4fec93afa66bf148c413fa7aa721",
}
KNOWN_R11_VAL_HASH={
    "H1":"20b1443dffc23ffd1981b58f0bf3bd62a745f3d5bb1267f3a2ae4a77be930401",
    "H4":"64f23589ecb10bf63c7c79526cef85bed5693f7ccccb1d5ed8b2c2d8c3330f18",
}

def time(value):
    t=pd.Timestamp(value)
    if t.tzinfo is None:raise ValueError("RBEST_NAIVE_TIME")
    return t.tz_convert("UTC")


def blank(reason, *, state="WAIT_DATA"):
    return {
        "direction":"WAIT","state":state,"reason":reason,
        "target":None,"issued":None,"closed":None,"observed":None,
        "buy_active":None,"sell_active":None,"buy_score":None,
        "buy_threshold":None,"buy_gate":None,"last_close":None,
        "execution_authority":False,
    }


def validate(payload,*,now):
    now=time(now)
    if (not isinstance(payload,dict)
            or payload.get("contract")!=CONTRACT
            or payload.get("source")!=SOURCE
            or payload.get("symbol")!="XAUUSD"
            or payload.get("research_only") is not True
            or payload.get("execution_authority") is not False
            or payload.get("execution_influence") is not False
            or payload.get("candidate_lineage")!=CANDIDATES):
        raise ValueError("RBEST_SNAPSHOT_CONTRACT_MISMATCH")
    issued=time(payload["as_of"])
    if not 0 <= (now-issued).total_seconds() <= 8*86400:
        raise ValueError("RBEST_PUBLICATION_TIME_INVALID")
    rows=payload.get("rows")
    if not isinstance(rows,dict) or set(rows)!=set(CANDIDATES):
        raise ValueError("RBEST_TIMEFRAME_SET_INVALID")
    result={}
    for tf in CANDIDATES:
        q=rows[tf]
        if not isinstance(q,dict) or q.get("execution_authority") is not False:
            raise ValueError("RBEST_ROW_CONTRACT_MISMATCH:"+tf)
        if tf in ("D1","W1"):
            if (q.get("direction")!="WAIT" or q.get("state")!="NOT_INFERENCED"
                    or q.get("reason")!="INDEPENDENT_MODEL_NOT_INFERENCED"):
                raise ValueError("RBEST_NONDEPLOYED_HEAD_FORGED:"+tf)
            result[tf]=blank("INDEPENDENT_MODEL_NOT_INFERENCED",state="NOT_INFERENCED")
            continue
        target=q.get("target_close_at")
        closed=q.get("closed_at")
        observed=q.get("observed_at")
        if q.get("state")=="WAIT_DATA":
            if q.get("direction")!="WAIT" or target is not None:
                raise ValueError("RBEST_FAKE_WAIT_DATA:"+tf)
            result[tf]=blank(q.get("reason") or "WAIT_DATA")
            continue
        if q.get("state")!="RESEARCH_SHADOW" or target is None or closed is None:
            raise ValueError("RBEST_UNEXPECTED_SHADOW_STATE:"+tf)
        sides=q.get("sides")
        if not isinstance(sides,dict) or set(sides)!={"BUY","SELL"}:
            raise ValueError("RBEST_SIDE_SCHEMA_MISMATCH:"+tf)
        b,s=sides["BUY"],sides["SELL"]
        if (b.get("version")!="R25" or s.get("version")!="R11"
                or type(b.get("active")) is not bool
                or type(s.get("active")) is not bool
                or (b.get("parity") or {}).get("parity")!="PASS"
                or (s.get("parity") or {}).get("parity")!="PASS"
                or (b.get("parity") or {}).get("n")!=KNOWN_R25_VALIDATION[tf][0]
                or (b.get("parity") or {}).get("correct")!=KNOWN_R25_VALIDATION[tf][1]
                or (s.get("parity") or {}).get("historical_train_sha256")
                    !=KNOWN_R11_TRAIN_HASH[tf]
                or (s.get("parity") or {}).get("historical_validation_sha256")
                    !=KNOWN_R11_VAL_HASH[tf]):
            raise ValueError("RBEST_ORIGINAL_POLICY_PARITY_FAILED:"+tf)
        expected="WAIT" if b["active"]==s["active"] else "BUY" if b["active"] else "SELL"
        if q.get("direction")!=expected:
            raise ValueError("RBEST_CONFLICT_RESOLUTION_INVALID:"+tf)
        ct,tt,obs,generated=time(closed),time(target),time(observed),time(q["generated_at"])
        hours=1 if tf=="H1" else 4
        if (tt-ct!=pd.Timedelta(hours=hours) or not ct<=obs<=generated<=issued
                or (generated-obs).total_seconds()>300
                or (issued-generated).total_seconds()>1200):
            raise ValueError("RBEST_BROKER_TIME_INVALID:"+tf)
        score=b.get("score")
        if (type(score) not in (int,float) or not math.isfinite(score)
                or not 0<=score<=1
                or b.get("threshold")!=.55
                or type(b.get("gate_pass")) is not bool):
            raise ValueError("RBEST_MODEL_SCORE_INVALID:"+tf)
        if now>=tt:
            result[tf]=blank("TARGET_CANDLE_EXPIRED")
            result[tf]["expired_at"]=tt.isoformat()
            result[tf]["issued"]=issued.isoformat()
            continue
        result[tf]={
            "direction":expected,
            "state":"RESEARCH_SHADOW" if expected!="WAIT" else "MODEL_ABSTAIN",
            "reason":q["reason"],"target":tt.isoformat(),
            "issued":issued.isoformat(),"closed":ct.isoformat(),
            "observed":obs.isoformat(),
            "buy_active":b["active"],"sell_active":s["active"],
            "buy_score":float(score),"buy_threshold":float(b["threshold"]),
            "buy_gate":b["gate"],"last_close":q.get("last_close"),
            "execution_authority":False,
        }
    return result


def _read(request,opener,api=False):
    with opener(request,timeout=6) as f:
        raw=f.read(250_001)
    if len(raw)>250_000:raise ValueError("RBEST_FEED_TOO_LARGE")
    p=json.loads(raw)
    if api:
        if (not isinstance(p,dict) or p.get("encoding")!="base64"
                or not isinstance(p.get("content"),str)):
            raise ValueError("RBEST_API_CONTENT_INVALID")
        try:raw=base64.b64decode(p["content"],validate=False)
        except (ValueError,binascii.Error) as e:
            raise ValueError("RBEST_API_B64_INVALID") from e
        p=json.loads(raw)
    return p


def fetch(*,now=None,opener=urlopen):
    now=time(now or datetime.now(UTC))
    headers={"User-Agent":"RIZAN-RBEST-specialists-readonly/1",
             "Cache-Control":"no-cache"}
    req=Request(RAW+"?slot="+str(int(now.timestamp()//30)),headers=headers)
    try:
        return validate(_read(req,opener),now=now)
    except (OSError,TimeoutError,ValueError,KeyError,TypeError):
        req2=Request(API,headers={**headers,"Accept":"application/vnd.github+json"})
        return validate(_read(req2,opener,True),now=now)

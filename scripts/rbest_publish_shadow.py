"""Atomic read-only publication of verified H1/H4 R25/R11 side heads.

D1/W1 archived side winners deliberately remain NOT_INFERENCED; there is no
point-in-time 2026 macro/news/COT parity or frozen independent model artifact.
Never manufacture BUY/SELL from historical win rates.
"""
from __future__ import annotations

import json
from datetime import UTC,datetime
from pathlib import Path
import pandas as pd

CONTRACT="RIZAN_BEST_SIDE_SHADOW_SNAPSHOT_V1"
SOURCE="CTRADER_MARKET_DATA_READ_ONLY"
REPORTS={"H1":"rbest-1h-shadow.json","H4":"rbest-4h-shadow.json"}
CANDIDATES={
    "H1":{"BUY":"R25","SELL":"R11"},
    "H4":{"BUY":"R25","SELL":"R11"},
    "D1":{"BUY":"R28.1","SELL":"R18"},
    "W1":{"BUY":"R27","SELL":"R24"},
}


def utc(value):
    q=pd.Timestamp(value)
    if q.tzinfo is None:raise ValueError("RBEST_TIMESTAMP_NO_TIMEZONE")
    return q.tz_convert("UTC")


def compose(root,now=None):
    now=utc(now or datetime.now(UTC))
    root=Path(root)
    rows={}
    for tf,path in REPORTS.items():
        f=root/path
        if not f.is_file() or f.stat().st_size>120_000:
            raise ValueError("RBEST_PROOF_MISSING_OR_OVERSIZED:"+tf)
        q=json.loads(f.read_text())
        if (q.get("contract")!="RIZAN_BEST_SIDE_SHADOW_V1"
                or q.get("tf")!=tf or q.get("research_only") is not True
                or q.get("source")!=SOURCE
                or q.get("execution_authority") is not False
                or q.get("execution_influence") is not False
                or not isinstance(q.get("sides"),dict)
                or set(q["sides"])!={"BUY","SELL"}):
            raise ValueError("RBEST_SOURCE_PROVENANCE_INVALID:"+tf)
        for side,version in CANDIDATES[tf].items():
            v=q["sides"][side]
            if v.get("version")!=version or type(v.get("active")) is not bool or (
                v.get("parity") or {}).get("parity")!="PASS":
                raise ValueError("RBEST_SIDE_PROOF_MISMATCH:"+tf+":"+side)
        generated=utc(q["generated_at"])
        closed=utc(q["candle_closed_at"])
        target=utc(q["target_close_at"])
        observed=utc(q["observed_at"])
        horizon=pd.Timedelta(hours=1 if tf=="H1" else 4)
        if (not -5 <= (now-generated).total_seconds() <= 1200
                or not closed <= observed <= generated <= now
                or target-closed!=horizon
                or (generated-observed).total_seconds()>300):
            raise ValueError("RBEST_PUBLICATION_TIME_OR_SOURCE_INVALID:"+tf)
        buy=q["sides"]["BUY"]["active"]
        sell=q["sides"]["SELL"]["active"]
        expected="WAIT" if buy==sell else "BUY" if buy else "SELL"
        if q.get("direction")!=expected:
            raise ValueError("RBEST_CONFLICT_RESOLUTION_MISMATCH:"+tf)
        valid=now < target
        direction=expected if valid else "WAIT"
        reason=q.get("reason") if valid else "TARGET_CANDLE_EXPIRED"
        if (valid and reason != ("SIDE_CONFLICT" if buy and sell
                                else "NO_SIDE_TRIGGER" if not buy and not sell
                                else "RESEARCH_CANDIDATE_SIGNAL")):
            raise ValueError("RBEST_CANDIDATE_REASON_MISMATCH:"+tf)
        rows[tf]={
            "direction":direction, "reason":reason,
            "state":"RESEARCH_SHADOW" if valid else "WAIT_DATA",
            "generated_at":generated.isoformat(),
            "closed_at":closed.isoformat() if valid else None,
            "target_close_at":target.isoformat() if valid else None,
            "observed_at":observed.isoformat() if valid else None,
            "last_close":q["last_close"] if valid else None,
            "sides":q["sides"] if valid else {},
            "execution_authority":False,
        }
    for tf in ("D1","W1"):
        rows[tf]={
            "direction":"WAIT", "reason":"INDEPENDENT_MODEL_NOT_INFERENCED",
            "state":"NOT_INFERENCED",
            "generated_at":None, "closed_at":None,"target_close_at":None,
            "observed_at":None, "last_close":None,
            "sides":{}, "execution_authority":False,
        }
    return {
        "contract":CONTRACT,"source":SOURCE,
        "symbol":"XAUUSD","research_only":True,
        "execution_authority":False,"execution_influence":False,
        "as_of":now.isoformat(),"candidate_lineage":CANDIDATES,
        "rows":rows,
        "warning":"R25/R11 H1/H4 are exploratory reconstructed heads. D1/W1 side winners are archived, NOT independently inferred. No forward validation or order authority.",
    }


if __name__=="__main__":
    path=Path("runtime/rbest-side-direction.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    result=compose("artifacts/rbest_inference")
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({tf:{"direction":v["direction"],"reason":v["reason"]}
                      for tf,v in result["rows"].items()}),flush=True)

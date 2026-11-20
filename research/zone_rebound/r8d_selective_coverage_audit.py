"""R8-D prospective selective-classification audit; research-only, stdlib.

Consumes precomputed REAL R6 event outcomes and point-in-time DXY features.
Never derives returns, re-labels market data, or touches broker execution.
Input rows: event_id, year, side, horizon, success, dxy_direction,
dxy_age_seconds, source_sha256, xau_source_sha256.
All outcomes must be from independently validated R6 ledger.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict
from statistics import NormalDist

_SHA=re.compile(r"^[0-9a-f]{64}$")
VALID_DXY={"UP","DOWN","FLAT","UNAVAILABLE"}
VALID_SIDE={"BUY","SELL"}
VALID_HORIZON={"H1","H4"}

def wilson(k,n,confidence=.95):
    if not n: return [None,None]
    z=NormalDist().inv_cdf(1-(1-confidence)/2)
    p=k/n; a=1+z*z/n
    mid=(p+z*z/(2*n))/a
    radius=z*math.sqrt((p*(1-p)+z*z/(4*n*n))/n)/a
    return [round(max(0,mid-radius)*100,2),round(min(1,mid+radius)*100,2)]

def audit(rows, *, max_age_seconds=120, min_side_n=100):
    """Fixed rule: aligned inverse USD momentum; no tuning on outcomes.

    A BUY is DXY DOWN, a SELL is DXY UP. FLAT and stale -> abstain.
    Baseline and accepted are both reported to expose selective attrition.
    """
    if max_age_seconds<=0 or min_side_n<1:
        raise ValueError("INVALID_PREDECLARED_LIMITS")
    seen=set()
    totals=defaultdict(lambda:{"n":0,"wins":0})
    used=defaultdict(lambda:{"n":0,"wins":0})
    missing=defaultdict(int)
    for r in rows:
        event=str(r["event_id"])
        side=str(r["side"]);h=str(r["horizon"]);year=int(r["year"])
        if not event or side not in VALID_SIDE or h not in VALID_HORIZON or not 2019<=year<=2026:
            raise ValueError("INVALID_EVENT")
        key=(event,h)
        if key in seen:raise ValueError("DUPLICATE_EVENT_HORIZON")
        seen.add(key)
        outcome=r["success"]
        if type(outcome) is not bool:raise ValueError("UNVERIFIED_OUTCOME_TYPE")
        for name in ("source_sha256","xau_source_sha256"):
            if not _SHA.fullmatch(str(r[name])):raise ValueError("MISSING_PROVENANCE_SHA")
        dxy=str(r["dxy_direction"])
        if dxy not in VALID_DXY:raise ValueError("BAD_DXY_DIRECTION")
        age=r["dxy_age_seconds"]
        if age is not None and (not isinstance(age,(int,float)) or not math.isfinite(age) or age<0):
            raise ValueError("INVALID_DXY_AGE")
        group=(year,h,side)
        totals[group]["n"]+=1;totals[group]["wins"]+=outcome
        if dxy=="UNAVAILABLE" or age is None or age>max_age_seconds:
            missing[group]+=1
        elif (side=="BUY" and dxy=="DOWN") or (side=="SELL" and dxy=="UP"):
            used[group]["n"]+=1;used[group]["wins"]+=outcome
    output=[]
    for key in sorted(totals):
        base=totals[key];selected=used[key]
        n=selected["n"];w=selected["wins"]
        output.append(dict(year=key[0],horizon=key[1],side=key[2],
            baseline_n=base["n"],baseline_wins=base["wins"],
            baseline_pct=round(100*base["wins"]/base["n"],2),
            baseline_wilson95=wilson(base["wins"],base["n"]),
            accepted_n=n,accepted_wins=w,accepted_pct=round(100*w/n,2) if n else None,
            accepted_wilson95=wilson(w,n),
            coverage_pct=round(100*n/base["n"],2),
            missing_or_stale_n=missing[key],
            gate="INSUFFICIENT_N" if n<min_side_n else (
                "WILSON_LOWER_60" if wilson(w,n)[0]>=60 else "NOT_PROVEN")))
    # Strict fail closed: no pooled side pass based on a single year or horizon.
    overall={}
    for h in ("H1","H4"):
        overall[h]={}
        for side in ("BUY","SELL"):
            group=[v for v in output if v["horizon"]==h and v["side"]==side]
            n=sum(v["accepted_n"] for v in group)
            w=sum(v["accepted_wins"] for v in group)
            overall[h][side]=dict(n=n,wins=w,wilson95=wilson(w,n),
                gate=("INSUFFICIENT_N" if n<min_side_n else
                      "LOWER_BOUND_60" if wilson(w,n)[0]>=60 else "NOT_PROVEN"),
                annual_cells=len(group))
        overall[h]["both_sides_pass"]=all(overall[h][s]["gate"]=="LOWER_BOUND_60"
                                           for s in ("BUY","SELL"))
    return {"status":"RESEARCH_ONLY","rows":len(seen),"annual_side":output,
            "overall":overall,"limitations":[
                "Input outcome/provenance must be independently verified; this tool does not validate market-data authenticity",
                "Repeated events and overlapping forward windows require cluster-aware confidence intervals",
                "Wilson bounds are descriptive, not a substitute for untouched prospective holdout",
                "Do not tune filters or quote-age on 2025-2026 reused test data",
                "No real data means no result or claimed 60 percent edge"]}

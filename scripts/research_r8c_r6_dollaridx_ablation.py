"""R8-C offline conditional R6/DOLLARIDXUSD evaluation; no execution authority.

Input event ledger MUST be independently generated from R6, with a SHA-pinned
manifest and immutable signal timestamps. No fabricated source or sample counts.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.research_r8_dollaridx_asof_audit import audit, causal_features

EXECUTION_AUTHORITY=False
EXECUTION_INFLUENCE=False
EVENT_FIELDS={"event_at","side","horizon_minutes","net_delta_usd","year"}
COST_USD_OZ=0.50

def verified_events(path:Path,manifest_path:Path):
    manifest=json.loads(manifest_path.read_text())
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.get("sha256_csv")!=digest or manifest.get("source_contract")!="RIZAN_XAU_M5_SWEEP_MSS_R6":
        raise ValueError("R6_LEDGER_PROVENANCE_MISMATCH")
    e=pd.read_csv(path)
    if not EVENT_FIELDS.issubset(e):raise ValueError("R6_LEDGER_COLUMNS_MISSING")
    if not e.side.isin(["BUY","SELL"]).all():raise ValueError("INVALID_SIDE")
    if not e.horizon_minutes.isin([60,240]).all():raise ValueError("INVALID_HORIZON")
    if not e.year.between(2019,2026).all():raise ValueError("INVALID_YEAR")
    t=e.event_at.astype(str)
    if not t.str.contains(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$",regex=True).all():
        raise ValueError("EVENT_UTC_OFFSET_MISSING")
    ts=pd.to_datetime(t,utc=True)
    if ts.duplicated().any():raise ValueError("DUPLICATE_EVENT_TIME")
    if not ts.is_monotonic_increasing:raise ValueError("EVENT_TIME_UNSORTED")
    if not (ts.dt.year.to_numpy()==e.year.to_numpy()).all():
        raise ValueError("EVENT_YEAR_MISMATCH")
    if not np.isfinite(e.net_delta_usd.to_numpy(dtype=float)).all():
        raise ValueError("INVALID_NET_DELTA")
    # A label must be computed after the entire forward H1/H4 observation
    # horizon; provenance must record the original label recipe.
    if manifest.get("label_recipe")!="NEXT_M1_OPEN_TO_HORIZON_CLOSE_COST_INCLUDED":
        raise ValueError("UNVERIFIED_LABEL_RECIPE")
    if manifest.get("cost_usd_oz")!=COST_USD_OZ:
        raise ValueError("COST_CONTRACT_MISMATCH")
    return e,dict(sha256_csv=digest,rows=len(e))

def wilson(w,n):
    if not n:return None
    z=1.95996398454
    p=w/n;d=1+z*z/n
    return round((p+z*z/(2*n)-z*np.sqrt(p*(1-p)/n+z*z/(4*n*n)))/d,4)

def evaluate(dxy,events):
    """Fixed preregistered abstention test; no fitted thresholds or hindsight."""
    f=causal_features(dxy,events[["event_at"]])
    merged=events.reset_index(drop=True).join(f.drop(columns=["event_at"]))
    results=[]
    for year in range(2019,2027):
        for horizon in (60,240):
            for side in ("BUY","SELL"):
                q=merged[(merged.year==year)&(merged.horizon_minutes==horizon)&(merged.side==side)]
                eligible=q[(q.status=="OK")&(q.complete_5_15_60==True)]
                usd_good="DOWN" if side=="BUY" else "UP"
                aligned=eligible[(eligible.dxy_direction_15m==usd_good)&
                                 (eligible.dxy_direction_60m==usd_good)]
                opposed=eligible[(eligible.dxy_direction_15m!=usd_good)&
                                 (eligible.dxy_direction_60m!=usd_good)]
                for label,group in (("BASELINE_ALL",q),("DXY_ELIGIBLE",eligible),
                                    ("DXY_ALIGNED",aligned),("DXY_OPPOSED",opposed)):
                    n=len(group);wins=int((group.net_delta_usd>0).sum())
                    results.append(dict(year=year,horizon=horizon,side=side,
                        cohort=label,n=n,wins=wins,accuracy=round(wins/n,4) if n else None,
                        wilson95_lower=wilson(wins,n),
                        eligible_coverage=round(len(eligible)/len(q),4) if len(q) else None))
    return {"contract":"R8C_R6_DOLLARIDX_CONDITIONAL_FALSIFICATION_V1",
            "execution_authority":False,"execution_influence":False,
            "cost_usd_oz":COST_USD_OZ,"results":results,
            "warning":"Historical source authenticity and true quote timing must be independently verified. No LIVE accuracy claim. Reused 2025-26 is NOT pristine holdout."}

def main():
    import argparse
    p=argparse.ArgumentParser()
    for x in ("dxy_csv","dxy_manifest","r6_events","r6_manifest","out"):
        p.add_argument("--"+x.replace("_","-"),type=Path,required=True)
    a=p.parse_args()
    dxy,dxy_meta=audit(a.dxy_csv,a.dxy_manifest)
    events,event_meta=verified_events(a.r6_events,a.r6_manifest)
    result=evaluate(dxy,events)
    result["source"]={"dxy":dxy_meta,"r6":event_meta}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"status":"RESEARCH_ONLY","r6_events":len(events),
                      "dxy_rows":len(dxy),"output":str(a.out)}))
if __name__=="__main__":main()

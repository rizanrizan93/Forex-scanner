"""R8-G: research-only, causal USD 5/15/60m filter for R6 event ledger.
Inputs: M1 DOLLARIDXUSD CSV open_utc,close and R6 events CSV
event_id,event_utc,year,side,horizon,success,xau_source_sha256.
A signal uses only fully closed M1 bars, with publication lag. Any missing
minute in the required window -> UNAVAILABLE. Never relabels XAU outcomes.
"""
import csv, json, math, sys
from datetime import timedelta
from pathlib import Path
from r8f_m1_source_gate import utc, audit
from r8d_selective_coverage_audit import audit as selective_audit

def join(m1_path, events_path, lag_seconds=120, max_age_seconds=300):
    source=audit(m1_path)
    bars={}
    for r in csv.DictReader(Path(m1_path).open(encoding="utf-8-sig",newline="")):
        bars[utc(r["open_utc"])]=float(r["close"])
    events=list(csv.DictReader(Path(events_path).open(encoding="utf-8-sig",newline="")))
    output=[]
    for r in events:
        event=utc(r["event_utc"])
        eligible=[t for t in bars if t+timedelta(seconds=60+lag_seconds)<=event]
        end=max(eligible) if eligible else None
        age=(event-(end+timedelta(minutes=1))).total_seconds() if end else None
        dirs={}
        for minutes in (5,15,60):
            # The return uses the last available closed bar versus the
            # bar ending exactly N minutes earlier. All intermediate
            # minute bars must exist, preventing hidden gap interpolation.
            required=[end-timedelta(minutes=i) for i in range(minutes+1)] if end else []
            if age is None or age>max_age_seconds or any(t not in bars for t in required):
                dirs[minutes]="UNAVAILABLE"
            else:
                change=bars[end]-bars[end-timedelta(minutes=minutes)]
                dirs[minutes]="UP" if change>0 else "DOWN" if change<0 else "FLAT"
        # Fixed consensus; disagreements abstain, no fitted thresholds.
        vals=list(dirs.values())
        consensus=vals[0] if len(set(vals))==1 and vals[0] in ("UP","DOWN") else "UNAVAILABLE"
        output.append(dict(event_id=r["event_id"],year=int(r["year"]),
            side=r["side"],horizon=r["horizon"],
            success={"true":True,"false":False}[r["success"].strip().lower()],
            dxy_direction=consensus,dxy_age_seconds=age,
            source_sha256=source["source_sha256"],
            xau_source_sha256=r["xau_source_sha256"],directions=dirs))
    clean=[{k:v for k,v in r.items() if k!="directions"} for r in output]
    result=selective_audit(clean,max_age_seconds=max_age_seconds)
    result["dxy_source_audit"]=source
    result["per_event_directions"]=[{"event_id":r["event_id"],"directions":r["directions"]} for r in output]
    return result

if __name__=="__main__":
    if len(sys.argv)!=3: raise SystemExit("usage: r8g_causal_usd_event_join.py DXY_M1.csv R6_EVENTS.csv")
    print(json.dumps(join(sys.argv[1],sys.argv[2]),indent=2))

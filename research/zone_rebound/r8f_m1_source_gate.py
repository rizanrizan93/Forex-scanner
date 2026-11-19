"""R8-F research-only causal DOLLARIDXUSD M1 source audit.
Input CSV: open_utc,close (numeric). UTC timestamps must end in Z.
Never infer a bar's availability from its open time. No production imports.
Usage: python r8f_m1_source_gate.py dollaridx_m1.csv
"""
import csv, hashlib, json, math, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def utc(s):
    if not isinstance(s,str) or not s.endswith("Z"):
        raise ValueError("UTC_Z_REQUIRED")
    d=datetime.fromisoformat(s[:-1]+"+00:00")
    if d.utcoffset()!=timedelta(0): raise ValueError("UTC_REQUIRED")
    return d

def audit(path, events=(), publication_lag_seconds=120, max_quote_age_seconds=300):
    p=Path(path)
    raw=p.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not rows: raise ValueError("EMPTY_SOURCE")
    if not {"open_utc","close"}.issubset(rows[0]): raise ValueError("MISSING_COLUMNS")
    bars=[]; previous=None; gaps=0
    for r in rows:
        t=utc(r["open_utc"])
        price=float(r["close"])
        if not math.isfinite(price) or price<=0: raise ValueError("INVALID_PRICE")
        if t.second or t.microsecond: raise ValueError("NOT_M1_ALIGNED")
        if previous is not None:
            if t<=previous: raise ValueError("DUPLICATE_OR_UNSORTED")
            if t-previous>timedelta(minutes=1): gaps+=1
        bars.append((t,price));previous=t
    results=[]
    for event in events:
        e=utc(event)
        # M1 bar closes at open+60s; delayed availability is enforced.
        eligible=[(t,p) for t,p in bars if t+timedelta(seconds=60+publication_lag_seconds)<=e]
        if not eligible:
            results.append({"event_utc":event,"status":"NO_ASOF_BAR"});continue
        t,p=eligible[-1]
        age=(e-(t+timedelta(minutes=1))).total_seconds()
        results.append({"event_utc":event,"status":"VALID" if age<=max_quote_age_seconds else "STALE",
                        "source_open_utc":t.isoformat().replace("+00:00","Z"),"quote_age_seconds":age,
                        "price":p if age<=max_quote_age_seconds else None})
    return {"source_sha256":digest,"source_rows":len(bars),"gap_intervals":gaps,
            "first_utc":bars[0][0].isoformat(),"last_utc":bars[-1][0].isoformat(),
            "asof_events":results,"accuracy_claim":"NONE","production_changes":False}

if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("usage: r8f_m1_source_gate.py FILE.csv")
    print(json.dumps(audit(sys.argv[1]),indent=2))

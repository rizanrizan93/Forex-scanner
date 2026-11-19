"""R8-I: pre-replay R6 ledger provenance and overlap audit (research only).
Rejects inconsistent event dates, duplicate event-horizon keys, invalid outcomes
and missing XAU provenance. Reports overlapping H1/H4 forward windows by side.
This audit does NOT certify source authenticity or infer any market performance.
"""
import csv, hashlib, json, re, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

SHA=re.compile(r"^[0-9a-f]{64}$")
FIELDS={"event_id","event_utc","year","side","horizon","success","xau_source_sha256"}
HORIZONS={"H1":timedelta(hours=1),"H4":timedelta(hours=4)}

def audit(path):
    raw=Path(path).read_bytes()
    reader=csv.DictReader(raw.decode("utf-8-sig").splitlines())
    if not reader.fieldnames or not FIELDS.issubset(reader.fieldnames):
        raise ValueError("MISSING_R6_COLUMNS")
    seen=set();identities={};groups=defaultdict(list);counts=defaultdict(int)
    for i,r in enumerate(reader,2):
        eid=r["event_id"].strip()
        ts=r["event_utc"].strip()
        if not eid or not ts.endswith("Z"): raise ValueError(f"BAD_EVENT_ID_OR_UTC:{i}")
        try: t=datetime.fromisoformat(ts[:-1]+"+00:00")
        except ValueError: raise ValueError(f"BAD_TIMESTAMP:{i}")
        year=int(r["year"]);side=r["side"];h=r["horizon"]
        if t.year!=year or not 2019<=year<=2026: raise ValueError(f"YEAR_MISMATCH:{i}")
        if side not in ("BUY","SELL") or h not in HORIZONS: raise ValueError(f"BAD_SIDE_HORIZON:{i}")
        if r["success"].strip().lower() not in ("true","false"): raise ValueError(f"BAD_OUTCOME:{i}")
        if not SHA.fullmatch(r["xau_source_sha256"]): raise ValueError(f"BAD_XAU_SHA:{i}")
        identity=(ts,year,side,r["xau_source_sha256"])
        if eid in identities and identities[eid]!=identity:
            raise ValueError(f"EVENT_IDENTITY_MISMATCH:{i}")
        identities[eid]=identity
        key=(eid,h)
        if key in seen: raise ValueError(f"DUPLICATE_EVENT_HORIZON:{i}")
        seen.add(key);counts[(year,h,side)]+=1;groups[(h,side)].append(t)
    overlap={}
    for (h,side),times in sorted(groups.items()):
        times.sort();last_end=None;overlaps=0
        for t in times:
            if last_end is not None and t<last_end: overlaps+=1
            end=t+HORIZONS[h]
            last_end=max(last_end or end,end)
        overlap[f"{h}_{side}"]={"n":len(times),"overlap_events":overlaps,
          "warning":"cluster-aware uncertainty required" if overlaps else "no same-side overlap"}
    return {"status":"PROVENANCE_SCHEMA_AUDIT_ONLY","ledger_sha256":hashlib.sha256(raw).hexdigest(),
      "n":len(seen),"by_year_horizon_side":[{"year":y,"horizon":h,"side":s,"n":n}
      for (y,h,s),n in sorted(counts.items())],"overlap":overlap,
      "limitations":["SHA fingerprints are not proof of authentic XAU source",
        "Cross-side and cross-horizon dependence still requires event clustering",
        "2025-2026 are previously exposed, not pristine holdout",
        "No accuracy claim without original event outcomes and market provenance"]}
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: r8i_ledger_integrity.py R6_EVENTS.csv")
    print(json.dumps(audit(sys.argv[1]),indent=2))

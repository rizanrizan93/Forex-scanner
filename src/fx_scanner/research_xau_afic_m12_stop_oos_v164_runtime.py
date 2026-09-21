from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from .research_xau_afic_m12_vs_m15_v162_runtime import _fetch_m1
from .research_xau_afic_m12_stop_oos_v164 import evaluate_v164
UTC=timezone.utc
START=datetime(2023,1,1,tzinfo=UTC); END=datetime(2025,1,1,tzinfo=UTC)
def run():
    rows=_fetch_m1(START,END)
    d=evaluate_v164(rows)
    p=Path(os.getenv("V164_OUTPUT","artifacts/xau-afic-m12-stop-oos-v164.json")); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    print("V164_ROWS "+json.dumps({"m1_rows":len(rows),"confirmations":d["confirmation_count"]},sort_keys=True))
    for variant,x in d["summary"].items(): print("V164_STOP "+json.dumps({"variant":variant,**x},sort_keys=True,default=str))
    print("V164_DECISION "+json.dumps({"diagnostic_only":True,"promotion":False,"observer_change":False},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(run())

from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_h1_break_diagnostic_v157 import evaluate_v157
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT);d=evaluate_v157(bars,evaluation_end=CONT["end"])
    p=Path(os.getenv("V157_OUTPUT","artifacts/xau-afic-h1-break-diagnostic-v157.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for variant,x in d["recent"].items():
        for h,defs in x["horizons"].items():
            for definition,m in defs.items():
                print("V157_BREAK "+json.dumps({"variant":variant,"horizon":h,"definition":definition,**m},sort_keys=True))
    print("V157_DECISION "+json.dumps({"diagnostic_only":True,"promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

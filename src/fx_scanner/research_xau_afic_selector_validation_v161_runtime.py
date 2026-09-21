from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_selector_validation_v161 import evaluate_v161
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    d=evaluate_v161(bars,evaluation_end=CONT["end"])
    p=Path(os.getenv("V161_OUTPUT","artifacts/xau-afic-selector-validation-v161.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for scope,x in d["scopes"].items():
        print("V161_SCOPE "+json.dumps({"scope":scope,**x},sort_keys=True,default=str))
    print("V161_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_public_robustness_v158 import evaluate_v158
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT);d=evaluate_v158(bars,evaluation_end=CONT["end"])
    p=Path(os.getenv("V158_OUTPUT","artifacts/xau-afic-public-robustness-v158.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for scope,models in d["scopes"].items():
        for key,x in models.items():
            print("V158_SCOPE "+json.dumps({"scope":scope,"key":key,**x},sort_keys=True,default=str))
    print("V158_DECISION "+json.dumps({"research_only":True,"promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

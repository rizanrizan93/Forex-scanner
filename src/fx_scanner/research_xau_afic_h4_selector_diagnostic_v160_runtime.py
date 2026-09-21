from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_h4_selector_diagnostic_v160 import evaluate_v160
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT);d=evaluate_v160(bars,evaluation_end=CONT["end"])
    p=Path(os.getenv("V160_OUTPUT","artifacts/xau-afic-h4-selector-diagnostic-v160.json"))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    print("V160_SAMPLE "+json.dumps(d["sample"],sort_keys=True))
    for target,features in d["diagnostics"].items():
        for feature,x in features.items():
            print("V160_FEATURE "+json.dumps({"target":target,"feature":feature,**x},sort_keys=True,default=str))
    print("V160_DECISION "+json.dumps({"diagnostic_only":True,"promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

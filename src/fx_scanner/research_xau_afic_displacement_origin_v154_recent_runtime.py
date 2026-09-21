from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_displacement_origin_v154 import evaluate_v154
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def _c(x):
    return {"forecasts":x["forecasts"],"directions":x["direction_counts"],"H16":x["horizons"]["16"],"H32":x["horizons"]["32"],"H64":x["horizons"]["64"]}
def run():
    bars=_fetch(CONT)
    d=evaluate_v154(bars,evaluation_end=CONT["end"])
    r=d["eras"].get("2025_2026YTD",{})
    p=Path(os.getenv("V154_RECENT_OUTPUT","artifacts/xau-afic-displacement-origin-v154-recent.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"reconstruction_basis":d["reconstruction_basis"],"contract":d["contract"],"recent":r},indent=2,sort_keys=True,default=str)+"\n")
    for v,x in r.items():
        print("V154_RECENT "+json.dumps({"variant":v,**_c(x)},sort_keys=True))
    print("V154_RECENT_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_runner_state_v156 import evaluate_v156
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT);d=evaluate_v156(bars,evaluation_end=CONT["end"]);r=d["eras"].get("2025_2026YTD",{})
    p=Path(os.getenv("V156_RECENT_OUTPUT","artifacts/xau-afic-runner-state-v156-recent.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"contract":d["contract"],"recent":r},indent=2,sort_keys=True,default=str)+"\n")
    for v,x in r.items():print("V156_RECENT "+json.dumps({"variant":v,**x},sort_keys=True,default=str))
    print("V156_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

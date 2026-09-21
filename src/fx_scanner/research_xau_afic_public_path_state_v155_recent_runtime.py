from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_public_path_state_v155 import evaluate_v155
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    d=evaluate_v155(bars,evaluation_end=CONT["end"])
    r=d["eras"].get("2025_2026YTD",{})
    p=Path(os.getenv("V155_RECENT_OUTPUT","artifacts/xau-afic-public-path-state-v155-recent.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"contract":d["contract"],"public_evidence":d["public_evidence"],"locked_fixture":d["locked_prospective_fixture"],"recent":r},indent=2,sort_keys=True,default=str)+"\n")
    for v,x in r.items():
        print("V155_RECENT "+json.dumps({"variant":v,**x},sort_keys=True,default=str))
    print("V155_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

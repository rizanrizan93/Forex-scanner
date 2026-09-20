from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_v110_prospective_observer_v113 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v113
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_v110_prospective_observer_v113"
def run()->int:
    now=datetime.now(tz=UTC)
    fetch_contract={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":now}
    bars=_fetch(fetch_contract)
    d=evaluate_v113(bars,pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],observed_at=now)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":now.isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V113_EVIDENCE_OUTPUT","artifacts/xau-v110-prospective-observer-v113.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    print("V113_STATE "+json.dumps(d["state_snapshot"],sort_keys=True,default=str))
    for name,x in d["strategy_authority"].items():
        print("V113_AUTH strategy="+name+" "+json.dumps(x,sort_keys=True,default=str))
    print("V113_MODE "+json.dumps({"selector_mode":d["selector_mode"],"active_satellites":d["active_satellites"]},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(run())

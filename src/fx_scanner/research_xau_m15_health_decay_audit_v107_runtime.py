from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_m15_health_decay_audit_v107 import ARTIFACT_CONTRACT,RESEARCH_VERSION,audit_m15_decay
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_m15_health_decay_audit_v107"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=audit_m15_decay(bars,costs=COST_SCENARIOS["V24_STRESS_4675"],pip_size=0.01,evaluation_end=CONTINUOUS["end"])
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V107_EVIDENCE_OUTPUT","artifacts/xau-m15-health-decay-audit-v107.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for s,x in d["strategies"].items():
        for a in x["activations"]: print("V107_ACTIVATION "+json.dumps(a,sort_keys=True))
        for q in x["deactivations"]: print("V107_DEACTIVATION "+json.dumps(q,sort_keys=True))
        for t in x["selected_trades"]: print("V107_SELECTED "+json.dumps(t,sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(run())

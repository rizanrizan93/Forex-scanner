from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_m15_exceptional_expansion_audit_v109 import ARTIFACT_CONTRACT,RESEARCH_VERSION,audit_v109
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_m15_exceptional_expansion_audit_v109"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=audit_v109(bars,costs=COST_SCENARIOS["V24_STRESS_4675"],pip_size=0.01,evaluation_end=CONTINUOUS["end"],era_windows=ERA_WINDOWS)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V109_EVIDENCE_OUTPUT","artifacts/xau-m15-exceptional-expansion-audit-v109.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for era,x in d["incidence_by_era"].items(): print("V109_INCIDENCE era="+era+" "+json.dumps(x,sort_keys=True))
    for s,eras in d["strategy_attribution"].items():
        for era,buckets in eras.items():
            for bucket,m in buckets.items():
                print(f"V109_ATTR strategy={s} era={era} bucket={bucket} {_metric_line(m)}")
    return 0
if __name__=="__main__": raise SystemExit(run())

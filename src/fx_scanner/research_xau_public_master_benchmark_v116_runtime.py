from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_public_master_benchmark_v116 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v116
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_public_master_benchmark_v116"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v116(
        bars,costs=COST_SCENARIOS["V24_STRESS_4675"],
        evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        era_windows=ERA_WINDOWS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V116_EVIDENCE_OUTPUT","artifacts/xau-public-master-benchmark-v116.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for s,x in d["strategies"].items():
        print(f"V116_FULL strategy={s} {_metric_line(x['full'])}")
        for era,m in x["eras"].items():
            print(f"V116_ERA strategy={s} era={era} {_metric_line(m)}")
        for y,m in x["annual"].items():
            if m["completed_trades"]:
                print(f"V116_YEAR strategy={s} year={y} {_metric_line(m)}")
    return 0
if __name__=="__main__":
    raise SystemExit(run())

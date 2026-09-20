from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_era_fingerprint_v97 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v97
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_era_fingerprint_v97"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v97(bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],era_windows=ERA_WINDOWS)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V97_EVIDENCE_OUTPUT","artifacts/xau-era-fingerprint-v97.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    print("V97_TOP "+json.dumps(d["top_recent_distinguishing_features"]))
    for f in d["top_recent_distinguishing_features"]:
        print("V97_EFFECT feature="+f+" "+json.dumps(d["recent_effect_sizes"][f],sort_keys=True))
        for era in ERA_WINDOWS:
            print("V97_PROFILE feature="+f+" era="+era+" "+json.dumps(d["era_profiles"][era][f],sort_keys=True))
    for s,x in d["strategy_metrics"].items():
        print(f"V97_STRATEGY id={s} full={_metric_line(x['full'])}")
        for era,m in x["eras"].items():
            print(f"V97_ERA id={s} era={era} {_metric_line(m)}")
        print("V97_MATCH id="+s+" "+json.dumps(x["recent_fingerprint_match_count"],sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(run())

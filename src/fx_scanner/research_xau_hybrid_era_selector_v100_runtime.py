from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hybrid_era_selector_v100 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v100
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_hybrid_era_selector_v100"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v100(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V100_EVIDENCE_OUTPUT","artifacts/xau-hybrid-era-selector-v100.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for k,m in d["full_period"].items(): print(f"V100_FULL id={k} {_metric_line(m)}")
    for era,x in d["eras"].items():
        for k in ("core","v98_selector","hybrid_selector"):
            print(f"V100_ERA id={k} era={era} {_metric_line(x[k])}")
            c=x["cash_fresh_100"][k]
            print(f"V100_CASH id={k} era={era} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} ruin={c['ruin']}")
        for strategy,attrs in x["raw_species_attribution"].items():
            for bucket,m in attrs.items():
                print(f"V100_ATTR strategy={strategy} era={era} bucket={bucket} {_metric_line(m)}")
    for k,m in d["species_masks"].items(): print("V100_MASK id="+k+" "+json.dumps(m,sort_keys=True,default=str))
    return 0
if __name__=="__main__": raise SystemExit(run())

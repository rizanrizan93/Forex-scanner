from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_strategy_specific_state_v110 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v110
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_strategy_specific_state_v110"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v110(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V110_EVIDENCE_OUTPUT","artifacts/xau-strategy-specific-state-v110.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for k,m in d["full_period"].items(): print(f"V110_FULL id={k} {_metric_line(m)}")
    for era,x in d["eras"].items():
        for k in ("core","selector"):
            print(f"V110_ERA id={k} era={era} {_metric_line(x[k])}")
            c=x["cash_fresh_100"][k]
            print(f"V110_CASH id={k} era={era} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} ruin={c['ruin']}")
        for s,m in x["selected_strategy_contribution"].items():
            print(f"V110_CONTRIB strategy={s} era={era} {_metric_line(m)}")
    for k,g in d["strategy_state_gates"].items(): print("V110_GATE id="+k+" "+json.dumps(g,sort_keys=True,default=str))
    return 0
if __name__=="__main__": raise SystemExit(run())

from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_capital_ladder_v90 import ARTIFACT_CONTRACT,COST_SCENARIO_ID,RESEARCH_VERSION,evaluate_v90
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch
from .storage.supabase_operational import SupabaseOperationalStore

UTC=timezone.utc
WORKER_NAME="dukascopy_xau_capital_ladder_v90"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
 "2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
 "2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
 "2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v90(bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],pip_size=0.01,costs=COST_SCENARIOS[COST_SCENARIO_ID],broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V90_EVIDENCE_OUTPUT","artifacts/xau-capital-ladder-v90.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    req=d["required_balance_for_minimum_lot"]
    print("V90_REQUIRED "+json.dumps(req,sort_keys=True))
    for k,v in d["starting_balance_ladder"].items():
        print(f"V90_LADDER start={k} ending={v['ending_balance_usd']} return_pct={v['return_pct']} opened={v['opened_trades']} risk_skips={v['risk_skips']} margin_skips={v['margin_skips']} guard_skips={v['planned_stop_guard_skips']} max_lot={v['max_lot_used']} hit1000={v['hit_1000']} hit1000_at={v['hit_1000_at']}")
        for label,cp in v["checkpoints"].items():
            print(f"V90_CP start={k} label={label} balance={cp['realized_balance_usd']}")
    return 0
if __name__=="__main__": raise SystemExit(run())

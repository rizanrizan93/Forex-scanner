from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_adaptive_family_selector_v118 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v118
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_adaptive_family_selector_v118"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}

def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v118(
        bars,
        evaluation_start=CONTINUOUS["start"],
        evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V118_EVIDENCE_OUTPUT","artifacts/xau-adaptive-family-selector-v118.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenarios"].items():
        for name,m in x["full"].items():
            print(f"V118_FULL cost={cost} id={name} {_metric_line(m)}")
        for era,v in x["eras"].items():
            for name,m in v.items():
                print(f"V118_ERA cost={cost} era={era} id={name} {_metric_line(m)}")
        c=x["cash_fixed_001_no_risk_cap"]
        print(f"V118_CASH cost={cost} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} margin_skips={c['margin_skips']} guard_skips={c['stopout_guard_skips']} dd_pct={c['max_realized_drawdown_pct']} ruin={c['ruin']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']}")
        print("V118_SELECTOR cost="+cost+" "+json.dumps(x["selector_diagnostics"],sort_keys=True,default=str))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

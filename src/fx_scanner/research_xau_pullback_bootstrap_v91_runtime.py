from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_pullback_bootstrap_v91 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v91
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_pullback_bootstrap_v91"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v91(bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V91_EVIDENCE_OUTPUT","artifacts/xau-pullback-bootstrap-v91.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    print(f"V91_BASELINE {_metric_line(d['baseline_v87_satellite_metrics'])}")
    for vid,x in d["variants"].items():
        cash=x["cash_100_risk5_dynamic"]; req=x["required_balance_for_minimum_lot"]
        print(f"V91_VARIANT id={vid} fills={x['filled_trades']} fill_fraction={x['fill_fraction']} {_metric_line(x['metrics'])}")
        print(f"V91_REQUIRED id={vid} "+json.dumps(req,sort_keys=True))
        print(f"V91_CASH id={vid} ending={cash['ending_balance_usd']} return_pct={cash['return_pct']} opened={cash['opened_trades']} risk_skips={cash['risk_skips']} margin_skips={cash['margin_skips']} guard_skips={cash['planned_stop_guard_skips']} max_lot={cash['max_lot_used']} hit1000={cash['hit_1000']} hit1000_at={cash['hit_1000_at']}")
        for era,m in x["era_metrics"].items():
            print(f"V91_ERA id={vid} era={era} {_metric_line(m)}")
    return 0
if __name__=="__main__": raise SystemExit(run())

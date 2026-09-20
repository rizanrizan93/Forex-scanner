from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_v110_robustness_v111 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v111
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_v110_robustness_v111"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v111(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,cost_scenarios=COST_SCENARIOS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V111_EVIDENCE_OUTPUT","artifacts/xau-v110-robustness-v111.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenario_results"].items():
        print(f"V111_FULL cost={cost} core={_metric_line(x['full']['core'])}")
        print(f"V111_FULL cost={cost} selector={_metric_line(x['full']['selector'])}")
        print("V111_CONCENTRATION cost="+cost+" "+json.dumps(x["profit_concentration"],sort_keys=True))
        if x["cash_fresh_100_2025YTD"] is not None:
            c=x["cash_fresh_100_2025YTD"]
            print(f"V111_CASH2025 cost={cost} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} ruin={c['ruin']}")
        for y,m in x["annual"].items():
            print(f"V111_YEAR cost={cost} year={y} selector={_metric_line(m['selector'])}")
        for y,m in x["start_sensitivity"].items():
            print(f"V111_START cost={cost} start={y} selector={_metric_line(m['selector'])}")
    return 0
if __name__=="__main__": raise SystemExit(run())

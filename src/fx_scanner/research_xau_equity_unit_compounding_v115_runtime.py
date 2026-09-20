from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_equity_unit_compounding_v115 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v115
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_equity_unit_compounding_v115"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v115(
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
    p=Path(os.getenv("V115_EVIDENCE_OUTPUT","artifacts/xau-equity-unit-compounding-v115.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenarios"].items():
        print(f"V115_SIGNAL cost={cost} {_metric_line(x['signal_metrics'])}")
        c=x["cash_equity_unit"]
        print(f"V115_CASH cost={cost} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} max_lot={c['max_lot_used']} reductions={c['size_reductions']} margin_skips={c['margin_skips']} guard_skips={c['stopout_guard_skips']} dd_pct={c['max_realized_drawdown_pct']} ruin={c['ruin']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']} hit10000={c['hit_10000']} hit10000_at={c['hit_10000_at']}")
        print("V115_CHECKPOINTS cost="+cost+" "+json.dumps(c["checkpoints"],sort_keys=True))
    return 0
if __name__=="__main__":
    raise SystemExit(run())

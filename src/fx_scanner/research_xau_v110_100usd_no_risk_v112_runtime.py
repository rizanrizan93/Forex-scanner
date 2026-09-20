from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_v110_100usd_no_risk_v112 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v112
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_v110_100usd_no_risk_v112"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v112(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,cost_scenarios=COST_SCENARIOS,
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V112_EVIDENCE_OUTPUT","artifacts/xau-v110-100usd-no-risk-v112.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenarios"].items():
        f=x["fixed_001_no_risk_cap"];g=x["dynamic_001_to_050_no_risk_cap"]
        print(f"V112_FIXED cost={cost} ending={f['ending_balance_usd']} return_pct={f['return_pct']} opened={f['opened_trades']} margin_skips={f['margin_skips']} guard_skips={f['stopout_guard_skips']} dd_pct={f['max_realized_drawdown_pct']} ruin={f['ruin']} hit1000={f['hit_1000']} hit1000_at={f['hit_1000_at']}")
        print(f"V112_DYNAMIC cost={cost} ending={g['ending_balance_usd']} return_pct={g['return_pct']} opened={g['opened_trades']} max_lot={g['max_lot_used']} margin_skips={g['margin_skips']} guard_skips={g['stopout_guard_skips']} dd_pct={g['max_realized_drawdown_pct']} ruin={g['ruin']} hit1000={g['hit_1000']} hit1000_at={g['hit_1000_at']} hit10000={g['hit_10000']} hit10000_at={g['hit_10000_at']}")
        print("V112_CHECKPOINTS cost="+cost+" "+json.dumps(g["checkpoints"],sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(run())

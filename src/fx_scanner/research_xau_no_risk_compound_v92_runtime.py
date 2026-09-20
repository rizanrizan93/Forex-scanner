from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from .research_xau_no_risk_compound_v92 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v92
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_no_risk_compound_v92"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v92(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V92_EVIDENCE_OUTPUT","artifacts/xau-no-risk-compound-v92.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    for vid,x in d["variants"].items():
        cash=x["cash"]
        print(f"V92_VARIANT id={vid} {_metric_line(x['signal_metrics'])}")
        print(f"V92_CASH id={vid} ending={cash['ending_balance_usd']} return_pct={cash['return_pct']} min_balance={cash['minimum_realized_balance_usd']} max_dd_pct={cash['max_realized_drawdown_pct']} opened={cash['opened_trades']} margin_skips={cash['margin_skips']} guard_skips={cash['planned_stop_guard_skips']} max_lot={cash['max_lot_used']} hit1000={cash['hit_1000']} hit1000_at={cash['hit_1000_at']} ruin={cash['ruin']}")
        for label,cp in cash["checkpoints"].items():
            print(f"V92_CP id={vid} label={label} balance={cp['realized_balance_usd']} active={cp['active_positions']}")
    return 0
if __name__=="__main__": raise SystemExit(run())

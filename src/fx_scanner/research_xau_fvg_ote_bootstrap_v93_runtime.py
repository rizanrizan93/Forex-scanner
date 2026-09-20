from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from .research_xau_fvg_ote_bootstrap_v93 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v93
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_fvg_ote_bootstrap_v93"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v93(
        bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS,
    )
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V93_EVIDENCE_OUTPUT","artifacts/xau-fvg-ote-bootstrap-v93.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    print(f"V93_BASELINE {_metric_line(d['baseline_v87_satellite_metrics'])}")
    for vid,x in d["variants"].items():
        r5=x["cash_100_risk5_dynamic"]; nr=x["cash_100_no_risk_compound"]
        print(f"V93_VARIANT id={vid} fills={x['filled_trades']} fill_fraction={x['fill_fraction']} {_metric_line(x['metrics'])}")
        print("V93_REQUIRED id="+vid+" "+json.dumps(x["required_balance_for_minimum_lot"],sort_keys=True))
        print(f"V93_RISK5 id={vid} ending={r5['ending_balance_usd']} return_pct={r5['return_pct']} opened={r5['opened_trades']} risk_skips={r5['risk_skips']} max_lot={r5['max_lot_used']} hit1000={r5['hit_1000']} hit1000_at={r5['hit_1000_at']}")
        print(f"V93_NORISK id={vid} ending={nr['ending_balance_usd']} return_pct={nr['return_pct']} opened={nr['opened_trades']} guard_skips={nr['planned_stop_guard_skips']} max_lot={nr['max_lot_used']} hit1000={nr['hit_1000']} hit1000_at={nr['hit_1000_at']} max_dd_pct={nr['max_realized_drawdown_pct']}")
        for era,m in x["era_metrics"].items():
            print(f"V93_ERA id={vid} era={era} {_metric_line(m)}")
    return 0
if __name__=="__main__": raise SystemExit(run())

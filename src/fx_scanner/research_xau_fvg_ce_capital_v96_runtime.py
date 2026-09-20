from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_fvg_ce_capital_v96 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v96
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
from .storage.supabase_operational import SupabaseOperationalStore
UTC=timezone.utc
WORKER_NAME="dukascopy_xau_fvg_ce_capital_v96"
CONTINUOUS={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
ERA_WINDOWS={
"2012_2018":(datetime(2012,1,1,tzinfo=UTC),datetime(2019,1,1,tzinfo=UTC)),
"2019_2024":(datetime(2019,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC)),
"2025_2026YTD":(datetime(2025,1,1,tzinfo=UTC),datetime(2026,9,20,tzinfo=UTC)),
}
def run()->int:
    bars=_fetch(CONTINUOUS)
    d=evaluate_v96(bars,evaluation_start=CONTINUOUS["start"],evaluation_end=CONTINUOUS["end"],pip_size=0.01,costs=COST_SCENARIOS["V24_STRESS_4675"],broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,era_windows=ERA_WINDOWS)
    details={"research_version":RESEARCH_VERSION,"policy_effect":"SHADOW_ONLY","execution_influence":False,"promotion_eligible":False,"observed_at":datetime.now(tz=UTC).isoformat(),"decision":d}
    try: SupabaseOperationalStore.from_env().write_heartbeat(WORKER_NAME,healthy=True,lag_seconds=0.0,details=details)
    except Exception as exc: details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"
    p=Path(os.getenv("V96_EVIDENCE_OUTPUT","artifacts/xau-fvg-ce-capital-v96.json"));p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},indent=2,sort_keys=True,default=str)+"\n")
    print(f"V96_SIGNAL {_metric_line(d['signal_metrics'])}")
    c=d["max_margin_100"]
    print(f"V96_MAXMARGIN ending={c['ending_balance_usd']} return_pct={c['return_pct']} min_balance={c['minimum_realized_balance_usd']} max_dd_pct={c['max_realized_drawdown_pct']} opened={c['opened_trades']} margin_skips={c['margin_skips']} max_lot={c['max_lot_used']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']} ruin={c['ruin']}")
    for start,x in d["risk5_capital_ladder"].items():
        print(f"V96_LADDER start={start} ending={x['ending_balance_usd']} return_pct={x['return_pct']} opened={x['opened_trades']} risk_skips={x['risk_skips']} max_lot={x['max_lot_used']} hit1000={x['hit_1000']} hit1000_at={x['hit_1000_at']}")
    return 0
if __name__=="__main__": raise SystemExit(run())

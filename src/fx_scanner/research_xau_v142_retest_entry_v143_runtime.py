from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch
from .research_xau_v142_retest_entry_v143 import ENTRY_MODES,evaluate_v143
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    data=evaluate_v143(bars,evaluation_end=CONT["end"],pip_size=.01,costs=COST_SCENARIOS["V24_STRESS_4675"],broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS)
    p=Path(os.getenv("V143_EVIDENCE_OUTPUT","artifacts/xau-v142-retest-entry-v143.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)+"\n")
    for mode in ENTRY_MODES:
        x=data["entries"][mode];m=x["full_metrics"];r=x["recent_metrics"];c=x["full_live100"];rc=x["recent_live100"]
        print("V143_ENTRY "+json.dumps({
            "mode":mode,"n":m["completed_trades"],"pf":m["profit_factor"],"exp":m["expectancy_r"],"dd_r":m["max_drawdown_r"],
            "median_risk_atr":x["risk_stats_full"].get("median_risk_atr"),"raw_fill_rate":x["fill_stats"]["raw_fill_rate"],
            "full_live100_opened":c["opened"],"full_live100_ending":c["ending_balance_usd"],"full_live100_dd_pct":c["max_realized_drawdown_pct"],
            "recent_n":r["completed_trades"],"recent_pf":r["profit_factor"],"recent_exp":r["expectancy_r"],
            "recent_live100_opened":rc["opened"],"recent_live100_ending":rc["ending_balance_usd"],
        },sort_keys=True))
    print("V143_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

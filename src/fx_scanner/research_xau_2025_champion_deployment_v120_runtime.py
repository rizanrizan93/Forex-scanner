from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_2025_champion_deployment_v120 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v120
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    d=evaluate_v120(
        bars,evaluation_end=CONT["end"],pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS
    )
    p=Path(os.getenv("V120_EVIDENCE_OUTPUT","artifacts/xau-2025-champion-deployment-v120.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenarios"].items():
        for label,w in x["windows"].items():
            print(f"V120_WINDOW cost={cost} start={label} selector={_metric_line(w['selector_metrics'])}")
            c=w["cash_fresh_100_fixed_001"]
            print(f"V120_CASH cost={cost} start={label} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} dd_pct={c['max_realized_drawdown_pct']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']}")
            for s,m in w["selected_strategy_contribution"].items():
                print(f"V120_CONTRIB cost={cost} start={label} strategy={s} {_metric_line(m)}")
    return 0
if __name__=="__main__": raise SystemExit(run())

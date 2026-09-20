from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_williams_adaptive_v119 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v119
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    d=evaluate_v119(bars,evaluation_start=CONT["start"],evaluation_end=CONT["end"],pip_size=0.01,cost_scenarios=COST_SCENARIOS,broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS)
    p=Path(os.getenv("V119_EVIDENCE_OUTPUT","artifacts/xau-williams-adaptive-v119.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for cost,x in d["scenarios"].items():
        for name,m in x["full"].items(): print(f"V119_FULL cost={cost} id={name} {_metric_line(m)}")
        for era,v in x["eras"].items():
            for name,m in v.items(): print(f"V119_ERA cost={cost} era={era} id={name} {_metric_line(m)}")
        c=x["cash_fixed_001_no_risk_cap"];print(f"V119_CASH cost={cost} ending={c['ending_balance_usd']} return_pct={c['return_pct']} opened={c['opened_trades']} dd_pct={c['max_realized_drawdown_pct']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']}")
        print("V119_SELECTOR cost="+cost+" "+json.dumps(x["selector_diagnostics"],sort_keys=True,default=str))
    return 0
if __name__=="__main__": raise SystemExit(run())

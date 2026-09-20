from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_2025_champion_decomposition_v121 import ARTIFACT_CONTRACT,RESEARCH_VERSION,evaluate_v121
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch,_metric_line
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def run():
    bars=_fetch(CONT)
    d=evaluate_v121(
        bars,evaluation_end=CONT["end"],pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V121_EVIDENCE_OUTPUT","artifacts/xau-2025-champion-decomposition-v121.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for name,x in d["portfolios"].items():
        print(f"V121_PORT id={name} {_metric_line(x['metrics'])}")
        c=x["cash"]
        print(f"V121_CASH id={name} ending={c['ending_balance_usd']} opened={c['opened_trades']} dd_pct={c['max_realized_drawdown_pct']} hit1000={c['hit_1000']} hit1000_at={c['hit_1000_at']}")
    print("V121_FIRST1000 "+json.dumps(d["full_v110_bootstrap_trace"]["first_1000_exit"],sort_keys=True,default=str))
    print("V121_BOOTSTRAP_ATTRIB "+json.dumps(d["full_v110_bootstrap_trace"]["realized_pnl_to_first_1000_by_strategy"],sort_keys=True,default=str))
    return 0
if __name__=="__main__": raise SystemExit(run())

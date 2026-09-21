from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS,_fetch
from .research_xau_v144_liquidity_forensic_v145 import evaluate_v145
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def _line(prefix,key,x):
    m=x.get("metrics",{})
    print(prefix+" "+json.dumps({
        "bucket":key,"n":x.get("n"),"pf":m.get("profit_factor"),"exp":m.get("expectancy_r"),"dd_r":m.get("max_drawdown_r"),
        "median_abs_gravity":x.get("median_abs_gravity"),"median_risk_atr":x.get("median_risk_atr"),"median_target_r":x.get("median_target_r"),
    },sort_keys=True))
def run():
    bars=_fetch(CONT)
    data=evaluate_v145(bars,evaluation_end=CONT["end"],pip_size=.01,costs=COST_SCENARIOS["V24_STRESS_4675"])
    p=Path(os.getenv("V145_EVIDENCE_OUTPUT","artifacts/xau-liquidity-forensic-v145.json"))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)+"\n")
    for k,x in data["by_family"].items():_line("V145_FAMILY",k,x)
    for k,x in data["by_pool"].items():_line("V145_POOL",k,x)
    for k,x in data["family_x_pool"].items():_line("V145_CROSS",k,x)
    for era,e in data["era"].items():
        _line("V145_ERA",era,e["all"])
        for k,x in e["family_x_pool"].items():_line("V145_ERA_CROSS",era+"|"+k,x)
    for k,x in data["outcome_geometry"].items():_line("V145_OUTCOME",k,x)
    print("V145_DECISION "+json.dumps({"diagnostic_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

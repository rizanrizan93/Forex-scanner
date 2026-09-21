from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch
from .research_xau_v121_capital_era_router_v149 import evaluate_v149
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def _c(x):
    m=x["metrics"]
    return {
        "ending":x["ending_balance_usd"],"dd_pct":x["max_realized_drawdown_pct"],
        "opened":x["opened"],"pf":m["profit_factor"],"exp":m["expectancy_r"],
        "first1000":None if x["first_1000_exit"] is None else x["first_1000_exit"]["at"],
        "ending_state":x["ending_state"],
    }
def run():
    bars=_fetch(CONT)
    d=evaluate_v149(
        bars,evaluation_end=CONT["end"],pip_size=.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V149_EVIDENCE_OUTPUT","artifacts/xau-capital-era-router-v149.json"))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for era,block in d["eras"].items():
        for v,x in block.items():
            print("V149_ERA "+json.dumps({"era":era,"variant":v,**_c(x)},sort_keys=True))
    for start,block in d["start_sensitivity"].items():
        for v,x in block.items():
            print("V149_START "+json.dumps({"start":start,"variant":v,**_c(x)},sort_keys=True))
    print("V149_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

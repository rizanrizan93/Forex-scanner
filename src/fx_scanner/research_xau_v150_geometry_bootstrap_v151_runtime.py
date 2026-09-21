from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC,COST_SCENARIOS,LEVERAGE_TIERS,_fetch
from .research_xau_v150_geometry_bootstrap_v151 import evaluate_v151
UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def _c(x):
    m=x["metrics"]
    return {"ending":x["ending_balance_usd"],"min_balance":x["minimum_balance_usd"],"dd_pct":x["max_realized_drawdown_pct"],"opened":x["opened"],"pf":m["profit_factor"],"exp":m["expectancy_r"],"families":x["opened_by_family"],"first_d1":x["first_d1_accept"],"first1000":x["first_1000_at"],"skips":x["skipped_by_reason"]}
def run():
    bars=_fetch(CONT)
    d=evaluate_v151(bars,evaluation_end=CONT["end"],pip_size=.01,costs=COST_SCENARIOS["V24_STRESS_4675"],broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS)
    p=Path(os.getenv("V151_EVIDENCE_OUTPUT","artifacts/xau-geometry-bootstrap-v151.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    print("V151_STREAMS "+json.dumps({k:v for k,v in d["stream_diagnostics"].items() if k!="v114_diagnostics"},sort_keys=True,default=str))
    for era,b in d["eras"].items():
        for v,x in b.items():print("V151_ERA "+json.dumps({"era":era,"variant":v,**_c(x)},sort_keys=True))
    for start,b in d["start_sensitivity"].items():
        for v,x in b.items():print("V151_START "+json.dumps({"start":start,"variant":v,**_c(x)},sort_keys=True))
    print("V151_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

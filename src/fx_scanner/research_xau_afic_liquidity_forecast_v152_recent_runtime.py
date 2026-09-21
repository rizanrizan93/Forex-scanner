from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch
from .research_xau_afic_liquidity_forecast_v152 import evaluate_v152
UTC=timezone.utc
CONT={"fetch_start":datetime(2024,1,1,tzinfo=UTC),"start":datetime(2025,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}
def _c(x):
    out={"forecasts":x["forecasts"],"directions":x["direction_counts"],"sources":x["terminal_sources"]}
    for h,v in x["horizons"].items():
        out["H"+h]={"n":v["n"],"tp1":v["tp1_hit_rate"],"terminal":v["terminal_hit_rate"],"stop":v["stop_rate"],"median_rr":v["median_terminal_rr"],"steps":v["step_hit_rates"]}
    return out
def run():
    bars=_fetch(CONT)
    d=evaluate_v152(bars,evaluation_end=CONT["end"])
    recent=d["eras"].get("2025_2026YTD",{})
    p=Path(os.getenv("V152_RECENT_OUTPUT","artifacts/xau-afic-liquidity-forecast-v152-recent.json"));p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"contract":d["contract"],"recent":recent},indent=2,sort_keys=True,default=str)+"\n")
    for v,x in recent.items():print("V152_RECENT "+json.dumps({"variant":v,**_c(x)},sort_keys=True))
    print("V152_RECENT_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(run())

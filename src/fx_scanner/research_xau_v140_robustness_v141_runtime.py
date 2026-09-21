from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import BROKER_SPEC, COST_SCENARIOS, LEVERAGE_TIERS, _fetch
from .research_xau_v135_macro_regime_v136_runtime import _load_macro
from .research_xau_v137_cftc_positioning_forensic_v138_runtime import _load_cftc
from .research_xau_v138_driver_interaction_forensic_v139_runtime import _load_driver_series
from .research_xau_v140_robustness_v141 import CANDIDATES, evaluate_v141

UTC=timezone.utc
CONT={"fetch_start":datetime(2011,1,1,tzinfo=UTC),"start":datetime(2012,1,1,tzinfo=UTC),"end":datetime(2026,9,20,tzinfo=UTC)}

def _compact(m):
    return {"n":m["completed_trades"],"pf":m["profit_factor"],"exp":m["expectancy_r"],"dd_r":m["max_drawdown_r"]}

def run():
    bars=_fetch(CONT)
    macro,_=_load_macro()
    drivers,_=_load_driver_series()
    cot,_=_load_cftc()
    super_stress=COST_SCENARIOS["V24_STRESS_4675"].stressed(spread_multiplier=1.25,slippage_multiplier=1.25)
    data=evaluate_v141(
        bars,
        macro_series=macro,
        driver_series=drivers,
        cot_raw_rows=cot,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        baseline_costs=COST_SCENARIOS["V24_STRESS_4675"],
        super_stress_costs=super_stress,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    path=Path(os.getenv("V141_EVIDENCE_OUTPUT","artifacts/xau-v140-robustness-v141.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,sort_keys=True,default=str)+"\n")
    for block_name in ("baseline","super_stress","h1_lag_1bar"):
        for cid in CANDIDATES:
            row=data[block_name][cid]
            print("V141_BLOCK "+json.dumps({
                "block":block_name,
                "candidate":cid,
                **_compact(row["full_metrics"]),
                "full_live100_opened":row["full_live100"]["opened"],
                "full_live100_ending":row["full_live100"]["ending_balance_usd"],
                "full_live100_max_dd_pct":row["full_live100"]["max_realized_drawdown_pct"],
                "recent_n":row["recent_metrics"]["completed_trades"],
                "recent_pf":row["recent_metrics"]["profit_factor"],
                "recent_exp":row["recent_metrics"]["expectancy_r"],
                "recent_live100_opened":row["recent_live100"]["opened"],
                "recent_live100_ending":row["recent_live100"]["ending_balance_usd"],
            },sort_keys=True))
    print("V141_DECISION "+json.dumps({"research_only":True,"production_promotion":False},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

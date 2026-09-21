from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch
from .research_xau_v130_epoch_forensic_v131 import evaluate_v131

UTC=timezone.utc
CONT={
    "fetch_start":datetime(2011,1,1,tzinfo=UTC),
    "start":datetime(2012,1,1,tzinfo=UTC),
    "end":datetime(2026,9,20,tzinfo=UTC),
}


def _net(m):
    return float(m["gross_profit_r"])-float(m["gross_loss_r"])


def run():
    bars=_fetch(CONT)
    d=evaluate_v131(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    p=Path(os.getenv("V131_EVIDENCE_OUTPUT","artifacts/xau-v130-epoch-forensic-v131.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")

    print("V131_COUNTS "+json.dumps(d["counts"],sort_keys=True))
    for side,m in d["by_side"].items():
        print("V131_SIDE "+json.dumps({
            "side":side,"n":m["completed_trades"],"pf":m["profit_factor"],
            "exp":m["expectancy_r"],"net_r":_net(m),"dd_r":m["max_drawdown_r"],
        },sort_keys=True))
    print("V131_TOP_PRE "+json.dumps([
        {"feature":k,"effect":d["effect_pre_positive_vs_nonpositive"].get(k)}
        for k in d["ranked_pre_separator_features"][:12]
    ],sort_keys=True))
    print("V131_TOP_RECENT "+json.dumps([
        {"feature":k,"effect":d["effect_recent_vs_pre_nonpositive"].get(k)}
        for k in d["ranked_recent_vs_prebad_features"][:12]
    ],sort_keys=True))
    worst=sorted(
        [x for x in d["epochs"] if x["outcome"]=="NONPOSITIVE"],
        key=lambda x:float(x["net_r"]),
    )[:12]
    print("V131_WORST "+json.dumps(worst,sort_keys=True))
    best=sorted(
        [x for x in d["epochs"] if x["outcome"]=="POSITIVE"],
        key=lambda x:float(x["net_r"]),
        reverse=True,
    )[:12]
    print("V131_BEST "+json.dumps(best,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(run())

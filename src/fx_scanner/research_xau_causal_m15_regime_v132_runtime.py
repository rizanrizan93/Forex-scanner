from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_causal_m15_regime_v132 import evaluate_v132
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
)

UTC=timezone.utc
CONT={
    "fetch_start":datetime(2011,1,1,tzinfo=UTC),
    "start":datetime(2012,1,1,tzinfo=UTC),
    "end":datetime(2026,9,20,tzinfo=UTC),
}

def _net(m):
    return float(m["gross_profit_r"])-float(m["gross_loss_r"])

def _passes(row):
    c=row["full_metrics"]
    ac={
        "full_min_trades":100,
        "full_min_pf":1.15,
        "full_min_expectancy_r":0.05,
        "full_max_drawdown_r":20.0,
        "each_pre2025_era_min_expectancy_r":0.0,
        "recent_min_pf":1.30,
        "recent_min_expectancy_r":0.10,
        "live100_recent_min_opened":30,
        "live100_recent_min_pf":1.20,
        "live100_recent_min_expectancy_r":0.0,
        "live100_recent_min_ending_balance":100.0,
    }
    if int(c["completed_trades"])<ac["full_min_trades"]: return False
    if c["profit_factor"] is None or float(c["profit_factor"])<ac["full_min_pf"]: return False
    if c["expectancy_r"] is None or float(c["expectancy_r"])<ac["full_min_expectancy_r"]: return False
    if float(c["max_drawdown_r"])>ac["full_max_drawdown_r"]: return False
    for era in ("2012_2018","2019_2024"):
        m=row["eras"][era]["metrics"]
        if m["expectancy_r"] is None or float(m["expectancy_r"])<0.0: return False
    rec=row["eras"]["2025_2026YTD"]
    rm=rec["metrics"]
    if rm["profit_factor"] is None or float(rm["profit_factor"])<ac["recent_min_pf"]: return False
    if rm["expectancy_r"] is None or float(rm["expectancy_r"])<ac["recent_min_expectancy_r"]: return False
    sim=rec["scenarios"]["LIVE_100_1_100_CAP50"]
    sm=sim["accepted_metrics"]
    if int(sim["opened"])<ac["live100_recent_min_opened"]: return False
    if sm["profit_factor"] is None or float(sm["profit_factor"])<ac["live100_recent_min_pf"]: return False
    if sm["expectancy_r"] is None or float(sm["expectancy_r"])<=ac["live100_recent_min_expectancy_r"]: return False
    if float(sim["ending_balance_usd"])<=ac["live100_recent_min_ending_balance"]: return False
    return True

def run():
    bars=_fetch(CONT)
    d=evaluate_v132(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V132_EVIDENCE_OUTPUT","artifacts/xau-causal-m15-regime-v132.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")
    for cid,row in d["candidates"].items():
        m=row["full_metrics"]
        print("V132_FULL "+json.dumps({
            "candidate":cid,
            "epoch_count":row["epoch_count"],
            "n":m["completed_trades"],
            "pf":m["profit_factor"],
            "exp":m["expectancy_r"],
            "net_r":_net(m),
            "dd_r":m["max_drawdown_r"],
            "passes":_passes(row),
        },sort_keys=True))
        for era in ("2012_2018","2019_2024","2025_2026YTD"):
            e=row["eras"][era]
            mm=e["metrics"]
            out={
                "candidate":cid,"era":era,
                "n":mm["completed_trades"],"pf":mm["profit_factor"],
                "exp":mm["expectancy_r"],"net_r":_net(mm),
            }
            if era=="2025_2026YTD":
                s=e["scenarios"]["LIVE_100_1_100_CAP50"]; sm=s["accepted_metrics"]
                out.update({
                    "live100_opened":s["opened"],
                    "live100_ending":s["ending_balance_usd"],
                    "live100_pf":sm["profit_factor"],
                    "live100_exp":sm["expectancy_r"],
                })
            print("V132_ERA "+json.dumps(out,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

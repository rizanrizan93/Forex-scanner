from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
)
from .research_xau_runtime_feasibility_v128 import evaluate_v128

UTC=timezone.utc
CONT={
    "fetch_start":datetime(2011,1,1,tzinfo=UTC),
    "start":datetime(2012,1,1,tzinfo=UTC),
    "end":datetime(2026,9,20,tzinfo=UTC),
}

def run():
    bars=_fetch(CONT)
    d=evaluate_v128(
        bars,evaluation_end=CONT["end"],pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V128_EVIDENCE_OUTPUT","artifacts/xau-runtime-feasibility-v128.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")

    print("V128_CURRENT_D1 "+json.dumps(d["current_v24_d1_reference"],sort_keys=True))
    for pid,payload in d["portfolios"].items():
        for sid,row in payload["runtime_scenarios"].items():
            m=row["accepted_metrics"]
            print("V128_SCENARIO "+json.dumps({
                "portfolio":pid,"scenario":sid,
                "available":row["available_trades"],"opened":row["opened_trades"],
                "acceptance_rate":row["acceptance_rate"],
                "ending_balance":row["ending_balance_usd"],
                "risk_skips":row["risk_skips"],
                "portfolio_risk_skips":row["portfolio_risk_skips"],
                "margin_cap_skips":row["margin_cap_skips"],
                "stopout_skips":row["stopout_skips"],
                "max_positions_skips":row["max_positions_skips"],
                "pf":m["profit_factor"],"exp":m["expectancy_r"],
                "net_r":m["gross_profit_r"]-m["gross_loss_r"],
            },sort_keys=True))
        print("V128_FLOOR_LIVE "+json.dumps({
            "portfolio":pid,
            **payload["single_trade_capital_floor_live_1_100"],
        },sort_keys=True))
        print("V128_FLOOR_DEMO "+json.dumps({
            "portfolio":pid,
            **payload["single_trade_capital_floor_demo_1_30"],
        },sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

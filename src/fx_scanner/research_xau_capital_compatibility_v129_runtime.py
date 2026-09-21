from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_capital_compatibility_v129 import evaluate_v129
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

def run():
    bars=_fetch(CONT)
    d=evaluate_v129(
        bars,evaluation_end=CONT["end"],pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V129_EVIDENCE_OUTPUT","artifacts/xau-capital-compatibility-v129.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")

    print("V129_MARGIN_BOUNDARY "+json.dumps(d["current_price_margin_only_min_balance"],sort_keys=True))
    for pid,payload in d["portfolios"].items():
        for sid,windows in payload["components"].items():
            for wid,row in windows.items():
                um=row["unconstrained_metrics"]
                print("V129_COMPONENT "+json.dumps({
                    "portfolio":pid,"strategy":sid,"window":wid,
                    "unconstrained_n":um["completed_trades"],
                    "unconstrained_pf":um["profit_factor"],
                    "unconstrained_exp":um["expectancy_r"],
                    "unconstrained_net_r":um["gross_profit_r"]-um["gross_loss_r"],
                },sort_keys=True))
                for aid,caps in row["scenarios"].items():
                    for cap,entry in caps.items():
                        sim=entry["simulation"]; m=sim["accepted_metrics"]; floor=entry["floor_distribution"]
                        print("V129_SCENARIO "+json.dumps({
                            "portfolio":pid,"strategy":sid,"window":wid,
                            "account":aid,"margin_cap_pct":int(cap),
                            "available":sim["available"],"opened":sim["opened"],
                            "acceptance_rate":sim["acceptance_rate"],
                            "ending_balance":sim["ending_balance_usd"],
                            "risk_skips":sim["risk_skips"],
                            "portfolio_risk_skips":sim["portfolio_risk_skips"],
                            "margin_skips":sim["margin_skips"],
                            "pf":m["profit_factor"],"exp":m["expectancy_r"],
                            "net_r":m["gross_profit_r"]-m["gross_loss_r"],
                            "floor_median":floor.get("median"),
                            "floor_p75":floor.get("p75"),
                            "pct_feasible_at_100":floor.get("pct_feasible_at_100"),
                            "pct_feasible_at_342":floor.get("pct_feasible_at_342"),
                        },sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(run())

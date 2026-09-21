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
from .research_xau_v126_gated_v24_m15_v130 import evaluate_v130

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
    d=evaluate_v130(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p=Path(os.getenv("V130_EVIDENCE_OUTPUT","artifacts/xau-v126-gated-v24-m15-v130.json"))
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,indent=2,sort_keys=True,default=str)+"\n")

    print("V130_EPOCHS "+json.dumps({"eligible_v126_epoch_count":d["eligible_v126_epoch_count"]},sort_keys=True))
    for pid,row in d["portfolios"].items():
        m=row["full_metrics"]
        print("V130_FULL "+json.dumps({
            "portfolio":pid,"n":m["completed_trades"],"pf":m["profit_factor"],
            "exp":m["expectancy_r"],"net_r":_net(m),"dd_r":m["max_drawdown_r"],
        },sort_keys=True))
        for era,e in row["eras"].items():
            mm=e["metrics"]
            print("V130_ERA "+json.dumps({
                "portfolio":pid,"era":era,"n":mm["completed_trades"],
                "pf":mm["profit_factor"],"exp":mm["expectancy_r"],"net_r":_net(mm),
            },sort_keys=True))
            if era=="2025_2026YTD":
                for account,caps in e["scenarios"].items():
                    for cap,s in caps.items():
                        am=s["accepted_metrics"]
                        print("V130_RECENT_SCENARIO "+json.dumps({
                            "portfolio":pid,"account":account,"margin_cap_pct":int(cap),
                            "available":s["available"],"opened":s["opened"],
                            "acceptance_rate":s["acceptance_rate"],
                            "ending_balance":s["ending_balance_usd"],
                            "pf":am["profit_factor"],"exp":am["expectancy_r"],
                            "net_r":_net(am),
                            "risk_skips":s["risk_skips"],
                            "portfolio_risk_skips":s["portfolio_risk_skips"],
                            "margin_skips":s["margin_skips"],
                        },sort_keys=True))
        for start,srow in row["start_sensitivity"].items():
            if start not in {"2012","2019","2025"}:
                continue
            mm=srow["metrics"]
            live50=srow["scenarios"]["LIVE_100_1_100"]["50"]
            lm=live50["accepted_metrics"]
            print("V130_START "+json.dumps({
                "portfolio":pid,"start":start,
                "n":mm["completed_trades"],"pf":mm["profit_factor"],"exp":mm["expectancy_r"],
                "live100_cap50_opened":live50["opened"],
                "live100_cap50_ending":live50["ending_balance_usd"],
                "live100_cap50_pf":lm["profit_factor"],
                "live100_cap50_exp":lm["expectancy_r"],
            },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(run())

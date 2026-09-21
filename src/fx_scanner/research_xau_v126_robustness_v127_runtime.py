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
from .research_xau_v126_robustness_v127 import evaluate_v127

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run():
    bars = _fetch(CONT)
    d = evaluate_v127(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p = Path(os.getenv("V127_EVIDENCE_OUTPUT", "artifacts/xau-v126-robustness-v127.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")

    m=d["base"]["metrics"]; c=d["base"]["continuous_100_cash"]
    print("V127_BASE "+json.dumps({
        "n":m["completed_trades"],"pf":m["profit_factor"],"exp":m["expectancy_r"],
        "net_r":m["gross_profit_r"]-m["gross_loss_r"],"dd_r":m["max_drawdown_r"],
        "ending_balance":c.get("ending_balance_usd"),"hit_1000":bool(c.get("hit_1000")),
        "hit_1000_at":c.get("hit_1000_at"),"eligible_epochs":d["base"]["eligible_epochs"],
    },sort_keys=True))
    for label,row in d["start_sensitivity"].items():
        mm=row["metrics"]; cc=row["fresh_100_cash"]
        print("V127_START "+json.dumps({
            "start":label,"n":mm["completed_trades"],"pf":mm["profit_factor"],
            "exp":mm["expectancy_r"],"net_r":mm["gross_profit_r"]-mm["gross_loss_r"],
            "ending_balance":cc.get("ending_balance_usd"),"opened":cc.get("opened_trades"),
            "hit_1000":bool(cc.get("hit_1000")),"hit_1000_at":cc.get("hit_1000_at"),
        },sort_keys=True))
    for rule,row in d["leave_one_rule_out"].items():
        mm=row["metrics"]; cc=row["continuous_100_cash"]
        print("V127_ABLATION "+json.dumps({
            "omitted":rule,"n":mm["completed_trades"],"pf":mm["profit_factor"],
            "exp":mm["expectancy_r"],"net_r":mm["gross_profit_r"]-mm["gross_loss_r"],
            "dd_r":mm["max_drawdown_r"],"ending_balance":cc.get("ending_balance_usd"),
            "eligible_epochs":row["eligible_epochs"],
        },sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

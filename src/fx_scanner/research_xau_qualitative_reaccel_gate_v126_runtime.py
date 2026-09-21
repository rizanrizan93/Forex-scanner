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
from .research_xau_qualitative_reaccel_gate_v126 import evaluate_v126

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run():
    bars = _fetch(CONT)
    d = evaluate_v126(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p = Path(os.getenv("V126_EVIDENCE_OUTPUT", "artifacts/xau-qualitative-reaccel-gate-v126.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")

    m = d["full_metrics"]
    cash = d["continuous_100_cash_2012_to_end"]
    print("V126_FULL " + json.dumps({
        "n": m["completed_trades"],
        "pf": m["profit_factor"],
        "exp": m["expectancy_r"],
        "net_r": m["gross_profit_r"] - m["gross_loss_r"],
        "dd_r": m["max_drawdown_r"],
        "ending_balance": cash.get("ending_balance_usd"),
        "opened": cash.get("opened_trades"),
        "hit_1000": bool(cash.get("hit_1000")),
        "first_hit_1000_at": cash.get("hit_1000_at"),
    }, sort_keys=True))
    print("V126_EPOCH_COUNTS " + json.dumps(d["epoch_counts"], sort_keys=True))
    print("V126_JAN2025 " + json.dumps({
        "found": d["jan2025"]["found"],
        "retained": d["jan2025"]["retained"],
    }, sort_keys=True))
    for era, e in d["eras"].items():
        mm = e["metrics"]
        cc = e["fresh_100_cash"]
        print("V126_ERA " + json.dumps({
            "era": era,
            "n": mm["completed_trades"],
            "pf": mm["profit_factor"],
            "exp": mm["expectancy_r"],
            "net_r": mm["gross_profit_r"] - mm["gross_loss_r"],
            "ending_balance": cc.get("ending_balance_usd"),
            "opened": cc.get("opened_trades"),
            "eligible_epochs": e["eligible_epoch_count"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

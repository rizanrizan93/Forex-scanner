from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_champion_onset_reaccel_v123 import evaluate_v123
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
)

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run():
    bars = _fetch(CONT)
    d = evaluate_v123(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p = Path(os.getenv("V123_EVIDENCE_OUTPUT", "artifacts/xau-champion-onset-reaccel-v123.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")

    for route_id, r in d["routes"].items():
        m = r["full_metrics"]
        cash = r["continuous_100_cash_2012_to_end"]
        print(
            "V123_ROUTE "
            + json.dumps(
                {
                    "route": route_id,
                    "n": m["completed_trades"],
                    "pf": m["profit_factor"],
                    "exp": m["expectancy_r"],
                    "net_r": m["gross_profit_r"] - m["gross_loss_r"],
                    "dd_r": m["max_drawdown_r"],
                    "ending_balance": cash.get("ending_balance"),
                    "opened": cash.get("opened_trades"),
                    "max_realized_dd_pct": cash.get("max_realized_drawdown_pct"),
                    "hit_1000": cash.get("first_hit_1000_at") is not None,
                    "first_hit_1000_at": cash.get("first_hit_1000_at"),
                    "epoch_count": r["epoch_count_full"],
                },
                sort_keys=True,
            )
        )
        for era, e in r["eras"].items():
            mm = e["metrics"]
            cc = e["fresh_100_cash"]
            print(
                "V123_ERA "
                + json.dumps(
                    {
                        "route": route_id,
                        "era": era,
                        "n": mm["completed_trades"],
                        "pf": mm["profit_factor"],
                        "exp": mm["expectancy_r"],
                        "net_r": mm["gross_profit_r"] - mm["gross_loss_r"],
                        "ending_balance": cc.get("ending_balance"),
                        "opened": cc.get("opened_trades"),
                        "epoch_count": e["epoch_count"],
                    },
                    sort_keys=True,
                )
            )
        print(
            "V123_EPOCHS_2024 "
            + json.dumps({"route": route_id, "epochs": r["epochs_2024_onward"]}, sort_keys=True)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

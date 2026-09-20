from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_2025_bootstrap_onset_forensic_v122 import evaluate_v122
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC, COST_SCENARIOS, LEVERAGE_TIERS, _fetch
)

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}

def run():
    bars = _fetch(CONT)
    d = evaluate_v122(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    p = Path(os.getenv("V122_EVIDENCE_OUTPUT", "artifacts/xau-2025-bootstrap-onset-forensic-v122.json"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2, sort_keys=True, default=str) + "\n")

    print("V122_COUNTS " + json.dumps(d["counts"], sort_keys=True))
    print("V122_MILESTONES " + json.dumps(d["milestones"], sort_keys=True, default=str))
    print("V122_TOP " + json.dumps(d["top_distinguishing_features"], sort_keys=True))
    for r in d["bootstrap_realized_d1"]:
        print(
            "V122_BOOT "
            + json.dumps(
                {
                    "strategy_id": r["strategy_id"],
                    "signal_at": r["signal_at"],
                    "entry_at": r["entry_at"],
                    "net_r": r["net_r"],
                    "cash_pnl_usd": r["cash_pnl_usd"],
                    "state": r.get("state"),
                    "species": r.get("species"),
                    "era_score": r.get("era_score"),
                    "quality_score": r.get("quality_score"),
                    "days_since_change_point": r.get("days_since_change_point"),
                    "risk_price": r.get("risk_price"),
                    "planned_loss_pct_of_balance": r.get("planned_loss_pct_of_balance"),
                },
                sort_keys=True,
            )
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(run())

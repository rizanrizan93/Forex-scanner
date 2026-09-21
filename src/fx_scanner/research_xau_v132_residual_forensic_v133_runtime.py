from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch
from .research_xau_v132_residual_forensic_v133 import evaluate_v133

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _net(m):
    return float(m["gross_profit_r"]) - float(m["gross_loss_r"])


def run():
    bars = _fetch(CONT)
    data = evaluate_v133(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    path = Path(
        os.getenv(
            "V133_EVIDENCE_OUTPUT",
            "artifacts/xau-v132-residual-forensic-v133.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    print("V133_COUNTS " + json.dumps(data["counts"], sort_keys=True))
    for era, m in data["by_era"].items():
        print(
            "V133_ERA "
            + json.dumps(
                {
                    "era": era,
                    "n": m["completed_trades"],
                    "pf": m["profit_factor"],
                    "exp": m["expectancy_r"],
                    "net_r": _net(m),
                    "dd_r": m["max_drawdown_r"],
                },
                sort_keys=True,
            )
        )
    print(
        "V133_TOP_PRE "
        + json.dumps(
            [
                {
                    "feature": key,
                    "effect": data["effect_pre_positive_vs_nonpositive"].get(key),
                }
                for key in data["ranked_pre_separator_features"][:12]
            ],
            sort_keys=True,
        )
    )
    print(
        "V133_TOP_RECENT "
        + json.dumps(
            [
                {
                    "feature": key,
                    "effect": data["effect_recent_vs_pre_nonpositive"].get(key),
                }
                for key in data["ranked_recent_vs_prebad_features"][:12]
            ],
            sort_keys=True,
        )
    )
    print("V133_EPOCHS " + json.dumps(data["epochs"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

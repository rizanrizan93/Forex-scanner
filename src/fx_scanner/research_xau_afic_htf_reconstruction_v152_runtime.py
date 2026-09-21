from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_afic_htf_reconstruction_v152 import VARIANTS, evaluate_v152
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
    "end": datetime(2026, 9, 21, tzinfo=UTC),
}


def run() -> int:
    bars = _fetch(CONT)
    data = evaluate_v152(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )
    path = Path(
        os.getenv(
            "V152_EVIDENCE_OUTPUT",
            "artifacts/xau-afic-htf-reconstruction-v152.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for variant in VARIANTS:
        row = data["variants"][variant.variant_id]
        m = row["full_metrics"]
        a = row["era_2012_2018"]
        b = row["era_2019_2024"]
        c = row["era_2025_2026"]
        cap = row["live100"]
        print(
            "V152_AFIC "
            + json.dumps(
                {
                    "variant": variant.variant_id,
                    "n": m["completed_trades"],
                    "wr": m["win_rate"],
                    "pf": m["profit_factor"],
                    "exp": m["expectancy_r"],
                    "dd_r": m["max_drawdown_r"],
                    "2012_2018_pf": a["profit_factor"],
                    "2019_2024_pf": b["profit_factor"],
                    "2025_2026_pf": c["profit_factor"],
                    "live100_opened": cap["opened"],
                    "live100_ending": cap["ending_balance_usd"],
                    "passed": row["filter_counts"]["passed"],
                    "short_passed": row["filter_counts"]["short_passed"],
                    "long_passed": row["filter_counts"]["long_passed"],
                },
                sort_keys=True,
            )
        )
    print(
        "V152_DECISION "
        + json.dumps(
            {
                "research_only": True,
                "production_promotion": False,
                "artifact": str(path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

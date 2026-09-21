from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_afic_symmetric_htf_v153 import VARIANTS, evaluate_v153
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
    data = evaluate_v153(
        bars,
        evaluation_end=CONT["end"],
        costs=COST_SCENARIOS["V24_STRESS_4675"],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
        pip_size=0.01,
    )
    path = Path(
        os.getenv(
            "V153_EVIDENCE_OUTPUT",
            "artifacts/xau-afic-symmetric-htf-v153.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    print("V153_BASE " + json.dumps(data["fill_stats"], sort_keys=True))
    for variant in VARIANTS:
        row = data["variants"][variant.variant_id]
        full = row["full_metrics"]
        long_m = row["full_by_direction"]["LONG"]
        short_m = row["full_by_direction"]["SHORT"]
        a = row["era_2012_2018"]
        b = row["era_2019_2024"]
        c = row["era_2025_2026"]
        cap = row["live100"]
        print(
            "V153_AFIC "
            + json.dumps(
                {
                    "variant": variant.variant_id,
                    "n": full["completed_trades"],
                    "wr": full["win_rate"],
                    "pf": full["profit_factor"],
                    "exp": full["expectancy_r"],
                    "dd_r": full["max_drawdown_r"],
                    "long_n": long_m["completed_trades"],
                    "long_pf": long_m["profit_factor"],
                    "short_n": short_m["completed_trades"],
                    "short_pf": short_m["profit_factor"],
                    "2012_2018_n": a["completed_trades"],
                    "2012_2018_pf": a["profit_factor"],
                    "2019_2024_n": b["completed_trades"],
                    "2019_2024_pf": b["profit_factor"],
                    "2025_2026_n": c["completed_trades"],
                    "2025_2026_pf": c["profit_factor"],
                    "live100_opened": cap["opened"],
                    "live100_ending": cap["ending_balance_usd"],
                    "passed": row["filter_counts"]["passed"],
                },
                sort_keys=True,
            )
        )
    print(
        "V153_DECISION "
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

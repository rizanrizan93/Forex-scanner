from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_false_onset_forensic_v125 import evaluate_v125
from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run():
    bars = _fetch(CONT)
    data = evaluate_v125(
        bars,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    path = Path(os.getenv("V125_EVIDENCE_OUTPUT", "artifacts/xau-false-onset-forensic-v125.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    print("V125_COUNTS " + json.dumps(data["counts"], sort_keys=True))
    print("V125_JAN2025 " + json.dumps(data["jan2025_onset"], sort_keys=True))
    print(
        "V125_TOP "
        + json.dumps(
            [
                {
                    "feature": key,
                    "effect": data["effect_sizes_prior_positive_vs_nonpositive"].get(key),
                }
                for key in data["ranked_false_onset_separators"][:12]
            ],
            sort_keys=True,
        )
    )

    bad_mid = [
        x for x in data["epochs"]
        if x["era"] == "2019_2024" and x["outcome_sign"] == "NONPOSITIVE_NET_R"
    ]
    bad_mid = sorted(bad_mid, key=lambda x: float(x["net_r"]))[:12]
    print("V125_WORST_MID " + json.dumps(bad_mid, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

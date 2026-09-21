from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    _fetch,
)
from .research_xau_v138_gold_driver_attribution_v139_runtime import _load_macro
from .research_xau_v139_causal_technical_states_v140 import evaluate_v140

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _compact(metrics):
    return {
        "n": metrics["completed_trades"],
        "pf": metrics["profit_factor"],
        "exp": metrics["expectancy_r"],
        "dd_r": metrics["max_drawdown_r"],
        "wr": metrics["win_rate"],
    }


def _print_block(name, payload):
    for era in ("full", "pre2025", "recent"):
        block = payload[era]
        print(
            "V140_STATE "
            + json.dumps(
                {
                    "block": name,
                    "era": era,
                    "all": _compact(block["metrics"]),
                    "states": {
                        k: _compact(v) for k, v in block["by_state"].items()
                    },
                    "state_x_risk": {
                        k: _compact(v) for k, v in block["state_x_risk"].items()
                    },
                },
                sort_keys=True,
            )
        )


def run():
    bars = _fetch(CONT)
    macro, meta = _load_macro()
    super_stress = COST_SCENARIOS["V24_STRESS_4675"].stressed(
        spread_multiplier=1.25,
        slippage_multiplier=1.25,
    )
    data = evaluate_v140(
        bars,
        macro_series=macro,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        baseline_costs=COST_SCENARIOS["V24_STRESS_4675"],
        super_stress_costs=super_stress,
    )
    data["macro_source_metadata"] = meta

    path = Path(
        os.getenv(
            "V140_EVIDENCE_OUTPUT",
            "artifacts/xau-v139-causal-technical-states-v140.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    _print_block("BASELINE", data["baseline"])
    _print_block("SUPER_STRESS", data["super_stress"])
    _print_block("H1_LAG_1BAR", data["one_h1_bar_lag"])
    print("V140_DECISION " + json.dumps({"diagnostic_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

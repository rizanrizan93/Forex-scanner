from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch
from .research_xau_v135_macro_regime_v136_runtime import _load_macro
from .research_xau_v136_structural_regime_forensic_v137 import evaluate_v137

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def _line(period, block):
    print(
        "V137_PERIOD "
        + json.dumps(
            {
                "period": period,
                "n": block["metrics"]["completed_trades"],
                "pf": block["metrics"]["profit_factor"],
                "exp": block["metrics"]["expectancy_r"],
                "dd_r": block["metrics"]["max_drawdown_r"],
                "regimes": {
                    k: {
                        "n": v["completed_trades"],
                        "pf": v["profit_factor"],
                        "exp": v["expectancy_r"],
                    }
                    for k, v in block["by_d1_regime"].items()
                },
                "maturities": {
                    k: {
                        "n": v["completed_trades"],
                        "pf": v["profit_factor"],
                        "exp": v["expectancy_r"],
                    }
                    for k, v in block["by_d1_maturity"].items()
                },
            },
            sort_keys=True,
        )
    )


def run():
    bars = _fetch(CONT)
    macro, meta = _load_macro()
    data = evaluate_v137(
        bars,
        macro_series=macro,
        evaluation_end=CONT["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS["V24_STRESS_4675"],
    )
    data["macro_source_metadata"] = meta

    path = Path(
        os.getenv(
            "V137_EVIDENCE_OUTPUT",
            "artifacts/xau-v136-structural-regime-forensic-v137.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    _line("FULL", data["full"])
    _line("PRE2025", data["pre2025"])
    _line("RECENT", data["recent"])
    print("V137_DECISION " + json.dumps({"diagnostic_only": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_afic_independent_path_confirm_v166 import evaluate_v166
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run() -> int:
    bars = _fetch(CONT)
    data = evaluate_v166(bars, evaluation_end=CONT["end"])

    path = Path(
        os.getenv(
            "V166_OUTPUT",
            "artifacts/xau-afic-independent-path-confirm-v166.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    )

    for scope, payload in [("FULL", data["full"]), *data["windows"].items()]:
        for rule, row in payload.items():
            print(
                "V166_SCOPE "
                + json.dumps(
                    {"scope": scope, "rule": rule, **row},
                    sort_keys=True,
                    default=str,
                )
            )

    control = data["full"]["STRICT_ENGULF_REJECT"]
    candidate = data["full"]["DIRECTIONAL_REJECTION"]
    print(
        "V166_DELTA "
        + json.dumps(
            {
                "scope": "FULL",
                "candidate_minus_control_scenarios":
                    candidate["scenarios"] - control["scenarios"],
                "candidate_minus_control_raw_confirmations":
                    candidate["raw_confirmation_count"] - control["raw_confirmation_count"],
                "candidate_minus_control_feasible":
                    candidate["geometry_feasible_count"] - control["geometry_feasible_count"],
                "candidate_minus_control_tp1_feasible":
                    None
                    if candidate["tp1_rate_given_feasible"] is None
                    or control["tp1_rate_given_feasible"] is None
                    else candidate["tp1_rate_given_feasible"]
                    - control["tp1_rate_given_feasible"],
                "candidate_minus_control_stop_feasible":
                    None
                    if candidate["stop_rate_given_feasible"] is None
                    or control["stop_rate_given_feasible"] is None
                    else candidate["stop_rate_given_feasible"]
                    - control["stop_rate_given_feasible"],
            },
            sort_keys=True,
        )
    )
    print(
        "V166_DECISION "
        + json.dumps(
            {
                "diagnostic_only": True,
                "promotion": False,
                "selector_changed": False,
                "execution_changed": False,
                "live_execution_enabled": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

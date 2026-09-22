from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_afic_m15_confirm_semantics_v165 import evaluate_v165
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run() -> int:
    bars = _fetch(CONT)
    data = evaluate_v165(bars, evaluation_end=CONT["end"])
    path = Path(
        os.getenv(
            "V165_OUTPUT",
            "artifacts/xau-afic-m15-confirm-semantics-v165.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    )

    for scope, payload in [("FULL", data["full"]), *data["windows"].items()]:
        for rule, row in payload["rules"].items():
            print(
                "V165_SCOPE "
                + json.dumps(
                    {"scope": scope, "rule": rule, **row},
                    sort_keys=True,
                    default=str,
                )
            )
        for rule, row in payload["overlap_vs_control"].items():
            print(
                "V165_OVERLAP "
                + json.dumps(
                    {"scope": scope, "candidate_rule": rule, **row},
                    sort_keys=True,
                    default=str,
                )
            )

    print(
        "V165_DECISION "
        + json.dumps(
            {
                "diagnostic_only": True,
                "promotion": False,
                "selector_changed": False,
                "execution_changed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

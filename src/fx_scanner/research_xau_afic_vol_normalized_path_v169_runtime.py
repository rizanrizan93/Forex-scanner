from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_afic_vol_normalized_path_v169 import evaluate_v169
from .research_xau_hierarchical_regime_router_v35_runtime import _fetch

UTC = timezone.utc
CONT = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}


def run() -> int:
    bars = _fetch(CONT)
    data = evaluate_v169(bars, evaluation_end=CONT["end"])
    path = Path(
        os.getenv(
            "V169_OUTPUT",
            "artifacts/xau-afic-vol-normalized-path-v169.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")

    for scope, payload in [("FULL", data["full"]), *data["windows"].items()]:
        for rule, row in payload.items():
            primary = row["barriers_atr"]["1.0"]
            print(
                "V169_SCOPE "
                + json.dumps(
                    {
                        "scope": scope,
                        "rule": rule,
                        "scenarios": row["scenarios"],
                        "zone_touched": row["zone_touched"],
                        "raw_confirmed": row["raw_confirmed"],
                        "confirm_1atr": primary["confirmed_forecast"],
                        "touch_1atr": primary["touch_baseline"],
                        "confirmation_lift_1atr": primary[
                            "confirmation_lift_favorable_first"
                        ],
                        "full_sequence_favorable_1atr_count": row[
                            "full_sequence_favorable_1atr_count"
                        ],
                        "full_sequence_favorable_1atr_rate": row[
                            "full_sequence_favorable_1atr_rate"
                        ],
                    },
                    sort_keys=True,
                    default=str,
                )
            )

    print(
        "V169_DECISION "
        + json.dumps(
            {
                "diagnostic_only": True,
                "promotion": False,
                "target_geometry_changed": False,
                "stop_geometry_changed": False,
                "execution_changed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

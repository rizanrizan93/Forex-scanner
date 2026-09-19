from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_h1_event_stability_v61 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v61,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    _fetch,
    _metric_line,
)
from .research_xau_v47_frozen_validation_v48_runtime import FULL_ERA
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_h1_event_stability_v61"


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v61(
        bars,
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
    )

    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "PUBLIC_HISTORY",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "promotion_eligible": False,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "data_source": "Dukascopy Bank public BID M15 via dukascopy-python",
        "decision": decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V61_EVIDENCE_OUTPUT",
            "artifacts/xau-h1-event-stability-v61.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "artifact_contract": ARTIFACT_CONTRACT,
                "contains_secrets": False,
                "details": details,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ) + "\n"
    )

    print(
        f"V61_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V61_COST cost={cost_id} "
            f"combined={_metric_line(payload['combined_full_period']['metrics'])}"
        )
        for year, year_payload in payload["combined_yearly_event_metrics"].items():
            for event, stats in year_payload.items():
                print(
                    f"V61_YEAR cost={cost_id} year={year} event={event} "
                    f"{_metric_line(stats['metrics'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

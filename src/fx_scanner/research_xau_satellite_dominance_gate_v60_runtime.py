from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    _fetch,
)
from .research_xau_satellite_dominance_gate_v60 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v60,
)
from .research_xau_v47_frozen_validation_v48_runtime import FULL_ERA
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_satellite_dominance_gate_v60"


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v60(
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
            "V60_EVIDENCE_OUTPUT",
            "artifacts/xau-satellite-dominance-gate-v60.json",
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
        f"V60_RESULT rows={len(bars)} decision={decision['decision']} "
        f"artifact={path} policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["cost_results"].items():
        print(
            f"V60_COST cost={cost_id} passed={int(payload['passed'])} "
            f"criteria={payload['criteria']} evidence={payload['evidence']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

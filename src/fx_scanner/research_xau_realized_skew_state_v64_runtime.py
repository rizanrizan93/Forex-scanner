from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    ERAS,
    _fetch,
    _metric_line,
)
from .research_xau_realized_skew_state_v64 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v64,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_realized_skew_state_v64"


def run() -> int:
    era_id = os.environ.get("V64_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V64_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v64(
        bars,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
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
            f"{WORKER_NAME}_{era_id}",
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V64_EVIDENCE_OUTPUT",
            f"artifacts/xau-realized-skew-state-v64-{era_id}.json",
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
        f"V64_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]
    print(
        f"V64_ALL era={era_id} "
        f"{_metric_line(stress['combined']['all']['metrics'])}"
    )
    for state, payload in stress["combined"]["states"].items():
        print(
            f"V64_STATE era={era_id} state={state} "
            f"{_metric_line(payload['metrics'])} "
            f"mean_skew={payload['mean_realized_skew']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

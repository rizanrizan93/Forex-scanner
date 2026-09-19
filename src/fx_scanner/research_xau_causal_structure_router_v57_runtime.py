from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_causal_structure_router_v57 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v57,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    ERAS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_causal_structure_router_v57"


def run() -> int:
    era_id = os.environ.get("V57_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V57_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v57(
        bars,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
    )

    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "PUBLIC_HISTORY_PLUS_BROKER_SNAPSHOT",
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
            "V57_EVIDENCE_OUTPUT",
            f"artifacts/xau-causal-structure-router-v57-{era_id}.json",
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
        f"V57_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]
    print(
        f"V57_CORE era={era_id} "
        f"{_metric_line(stress['core_d1_classic']['metrics'])}"
    )
    print(
        f"V57_BASE era={era_id} "
        f"{_metric_line(stress['base_route_ungated']['metrics'])}"
    )
    for router_type, payload in stress["routers"].items():
        print(
            f"V57_ROUTER era={era_id} type={router_type} "
            f"gated={_metric_line(payload['gated_satellite']['metrics'])} "
            f"portfolio={_metric_line(payload['gated_d1_plus_satellite']['metrics'])}"
        )
        for stream, gate in payload["streams"].items():
            print(
                f"V57_STREAM era={era_id} type={router_type} stream={stream} "
                f"candidate={gate['candidate_trades']} kept={gate['kept_trades']} "
                f"activation={gate['activation_fraction']} "
                f"era_gated={_metric_line(gate['era_gated_metrics'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

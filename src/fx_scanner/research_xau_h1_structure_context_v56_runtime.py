from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_h1_structure_context_v56 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v56,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    ERAS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_h1_structure_context_v56"


def _line(payload):
    return _metric_line(payload["metrics"]) if payload else "n=0"


def run() -> int:
    era_id = os.environ.get("V56_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V56_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v56(
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
            "V56_EVIDENCE_OUTPUT",
            f"artifacts/xau-h1-structure-context-v56-{era_id}.json",
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
        f"V56_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]["combined_gated_satellite"]
    print(f"V56_ALL era={era_id} {_line(stress['all'])}")
    for group in ("structure_state", "last_break_event", "last_break_direction"):
        for key, payload in stress[group].items():
            print(
                f"V56_BUCKET era={era_id} group={group} key={key} "
                f"{_line(payload)}"
            )
    print(f"V56_BREAK_AGE era={era_id} {stress['break_age_h1_bars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_canonical_ict_context_v65 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v65,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    ERAS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_canonical_ict_context_v65"


def run() -> int:
    era_id = os.environ.get("V65_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V65_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v65(
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
            "V65_EVIDENCE_OUTPUT",
            f"artifacts/xau-canonical-ict-context-v65-{era_id}.json",
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
        f"V65_RESULT era={era_id} rows={len(bars)} "
        f"contexts={decision['ict_context_signals']} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]["combined"]
    print(f"V65_ALL era={era_id} {_metric_line(stress['all']['metrics'])}")
    for feature in (
        "execution_ready",
        "fvg_retest",
        "order_block_retest",
        "ote_retest",
        "premium_discount_ok",
        "swept_liquidity",
        "anti_chase_ok",
        "external_target_available",
    ):
        for state, payload in stress[feature].items():
            if int(payload["trades"]) > 0:
                print(
                    f"V65_FEATURE era={era_id} feature={feature} state={state} "
                    f"{_metric_line(payload['metrics'])}"
                )
    for bucket, payload in stress["confluence_count"].items():
        if int(payload["trades"]) > 0:
            print(
                f"V65_CONFLUENCE era={era_id} bucket={bucket} "
                f"{_metric_line(payload['metrics'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_h4_pullback_continuation_v86 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v86,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    ERAS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_h4_pullback_continuation_v86"


def run() -> int:
    era_id=os.environ.get("V86_ERA","").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V86_ERA_INVALID:{era_id}")
    era=ERAS[era_id]
    bars=_fetch(era)
    decision=evaluate_v86(
        bars,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
    )
    details={
        "research_version":RESEARCH_VERSION,
        "environment":"PUBLIC_HISTORY",
        "policy_effect":"SHADOW_ONLY",
        "execution_influence":False,
        "promotion_eligible":False,
        "observed_at":datetime.now(tz=UTC).isoformat(),
        "data_source":"Dukascopy Bank public BID M15 via dukascopy-python",
        "decision":decision,
    }
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            f"{WORKER_NAME}_{era_id}",
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"

    path=Path(os.getenv("V86_EVIDENCE_OUTPUT",f"artifacts/xau-h4-pullback-continuation-v86-{era_id}.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract":ARTIFACT_CONTRACT,
        "contains_secrets":False,
        "details":details,
    },indent=2,sort_keys=True,default=str)+"\n")

    print(
        f"V86_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id,payload in decision["scenario_results"].items():
        print(
            f"V86_COST era={era_id} cost={cost_id} "
            f"all={_metric_line(payload['all']['metrics'])} "
            f"long={_metric_line(payload['long']['metrics'])} "
            f"short={_metric_line(payload['short']['metrics'])}"
        )
    return 0


if __name__=="__main__":
    raise SystemExit(run())

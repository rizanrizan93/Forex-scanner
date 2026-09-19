from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    ERAS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .research_xau_secular_regime_router_v46 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v46,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_secular_regime_router_v46"


def run() -> int:
    era_id = os.environ.get("V46_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V46_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v46(
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

    path = Path(os.getenv("V46_EVIDENCE_OUTPUT", f"artifacts/xau-secular-regime-router-v46-{era_id}.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V46_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]
    print(f"V46_SECULAR_DAYS era={era_id} {stress['secular_day_counts']}")
    for route, payload in stress["routes"].items():
        print(
            f"V46_ROUTE era={era_id} id={route} "
            f"{_metric_line(payload['metrics'])} tpd={payload['trades_per_day']} "
            f"loss_streak={payload['max_losing_streak']}"
        )
    for pid, payload in stress["portfolios"].items():
        print(
            f"V46_PORTFOLIO era={era_id} id={pid} "
            f"{_metric_line(payload['metrics'])} tpd={payload['trades_per_day']} "
            f"loss_streak={payload['max_losing_streak']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

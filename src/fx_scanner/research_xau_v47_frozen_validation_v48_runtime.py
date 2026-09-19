from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .research_xau_v47_frozen_validation_v48 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RESEARCH_VERSION,
    evaluate_v48,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_frozen_validation_v48"

FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v48(
        bars,
        pip_size=0.01,
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
        cost_scenarios=COST_SCENARIOS,
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
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V48_EVIDENCE_OUTPUT",
            "artifacts/xau-v47-frozen-validation-v48.json",
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
        f"V48_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, scenario in decision["scenarios"].items():
        print(
            f"V48_COST cost={cost_id} "
            f"core={_metric_line(scenario['core_d1_classic']['metrics'])} "
            f"satellite={_metric_line(scenario['satellite']['metrics'])} "
            f"portfolio={_metric_line(scenario['portfolio']['metrics'])} "
            f"verdict={scenario['verdict']}"
        )
        for year, payload in scenario["annual"].items():
            print(
                f"V48_YEAR cost={cost_id} year={year} "
                f"{_metric_line(payload['metrics'])} "
                f"tpd={payload['trades_per_day']}"
            )
        for window, payload in scenario["rolling_3y"].items():
            print(
                f"V48_ROLL3Y cost={cost_id} window={window} "
                f"{_metric_line(payload['metrics'])}"
            )
    print(f"V48_CROSS_COST {decision['cross_cost_checks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

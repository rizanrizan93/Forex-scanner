from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    _fetch,
    _metric_line,
)
from .research_xau_satellite_attribution_v59 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v59,
)
from .research_xau_v47_frozen_validation_v48_runtime import FULL_ERA
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_satellite_attribution_v59"


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v59(
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
            "V59_EVIDENCE_OUTPUT",
            "artifacts/xau-satellite-attribution-v59.json",
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
        f"V59_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V59_COST cost={cost_id} "
            f"core={_metric_line(payload['core']['metrics'])} "
            f"satellite={_metric_line(payload['satellite']['metrics'])} "
            f"portfolio={_metric_line(payload['portfolio']['metrics'])} "
            f"full_delta={payload['full_period_attribution']}"
        )
        print(
            f"V59_SUMMARY cost={cost_id} "
            f"{payload['attribution_summary']}"
        )
        for window, row in payload["rolling_3y"].items():
            print(
                f"V59_ROLL3Y cost={cost_id} window={window} "
                f"core_net={row['delta']['core_pf']} "
                f"portfolio_pf={row['delta']['portfolio_pf']} "
                f"incremental_r={row['delta']['incremental_net_r']} "
                f"dd_delta={row['delta']['drawdown_delta_r']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

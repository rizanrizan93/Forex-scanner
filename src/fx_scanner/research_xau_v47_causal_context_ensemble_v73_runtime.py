from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch, _metric_line
from .research_xau_v47_causal_context_ensemble_v73 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RESEARCH_VERSION,
    evaluate_v73,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_causal_context_ensemble_v73"
FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v73(
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

    path = Path(os.getenv("V73_EVIDENCE_OUTPUT", "artifacts/xau-v47-causal-context-ensemble-v73.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V73_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V73_COST cost={cost_id} "
            f"baseline={_metric_line(payload['baseline_v47_satellite']['metrics'])} "
            f"overlay={_metric_line(payload['causal_overlay_satellite']['metrics'])} "
            f"base_port={_metric_line(payload['baseline_d1_plus_satellite']['metrics'])} "
            f"overlay_port={_metric_line(payload['overlay_d1_plus_satellite']['metrics'])} "
            f"diag={payload['prediction_diagnostics']}"
        )
        for year, row in payload["annual"].items():
            if int(row["baseline"]["trades"]) > 0:
                print(
                    f"V73_YEAR cost={cost_id} year={year} "
                    f"baseline={_metric_line(row['baseline']['metrics'])} "
                    f"overlay={_metric_line(row['overlay']['metrics'])} "
                    f"delta_r={row['overlay_delta_net_r']} "
                    f"dd_delta={row['overlay_delta_drawdown_r']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

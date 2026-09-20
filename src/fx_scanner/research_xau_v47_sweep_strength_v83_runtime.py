from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch, _metric_line
from .research_xau_v47_sweep_strength_v83 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RAW_FEATURES,
    RESEARCH_VERSION,
    evaluate_v83,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_sweep_strength_v83"
FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v83(
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

    path = Path(os.getenv("V83_EVIDENCE_OUTPUT", "artifacts/xau-v47-sweep-strength-v83.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V83_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V83_COST cost={cost_id} "
            f"satellite={_metric_line(payload['satellite']['metrics'])}"
        )
        for window, row in payload["diagnostic_windows"].items():
            print(
                f"V83_WINDOW cost={cost_id} window={window} "
                f"sweep={_metric_line(row['sweep']['metrics'])} "
                f"non_sweep={_metric_line(row['non_sweep']['metrics'])}"
            )
            for feature in RAW_FEATURES:
                summary=row["raw_feature_relationships"][feature]
                print(
                    f"V83_FEATURE cost={cost_id} window={window} feature={feature} "
                    f"n={summary['n']} rho={summary['spearman_vs_net_r']} "
                    f"winner_mean={summary['winner_mean']} loser_mean={summary['loser_mean']} "
                    f"winner_median={summary['winner_median']} loser_median={summary['loser_median']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

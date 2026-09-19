from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_h1_event_stability_v61 import FULL_END, FULL_START
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .research_xau_nested_event_router_v62 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v62,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_nested_event_router_v62"

FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v62(
        bars,
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
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V62_EVIDENCE_OUTPUT",
            "artifacts/xau-nested-event-router-v62.json",
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
        f"V62_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V62_COST cost={cost_id} "
            f"core={_metric_line(payload['core']['metrics'])} "
            f"v47sat={_metric_line(payload['v47_satellite']['metrics'])} "
            f"nested={_metric_line(payload['nested_satellite']['metrics'])} "
            f"v47port={_metric_line(payload['v47_portfolio']['metrics'])} "
            f"nestedport={_metric_line(payload['nested_portfolio']['metrics'])} "
            f"summary={payload['summary']}"
        )
        for event, gate in payload["event_gates"].items():
            print(
                f"V62_EVENT cost={cost_id} event={event} "
                f"candidate={gate['candidate_trades']} kept={gate['kept_trades']} "
                f"activation={gate['activation_fraction']} "
                f"nested={_metric_line(gate['nested_era_metrics'])}"
            )
        for year, row in payload["annual"].items():
            if (
                int(row["v47_satellite"]["trades"]) > 0
                or int(row["nested_satellite"]["trades"]) > 0
            ):
                print(
                    f"V62_YEAR cost={cost_id} year={year} "
                    f"v47sat={_metric_line(row['v47_satellite']['metrics'])} "
                    f"nested={_metric_line(row['nested_satellite']['metrics'])} "
                    f"nested_vs_core={row['nested_incremental_vs_core_r']} "
                    f"nested_vs_v47={row['nested_delta_vs_v47_r']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

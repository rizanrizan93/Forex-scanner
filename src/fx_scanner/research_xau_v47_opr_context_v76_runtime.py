from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import COST_SCENARIOS, _fetch, _metric_line
from .research_xau_v47_opr_context_v76 import (
    ARTIFACT_CONTRACT,
    FULL_END,
    FULL_START,
    RESEARCH_VERSION,
    evaluate_v76,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_v47_opr_context_v76"
FULL_ERA = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": FULL_START,
    "end": FULL_END,
}


def run() -> int:
    bars = _fetch(FULL_ERA)
    decision = evaluate_v76(
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

    path = Path(os.getenv("V76_EVIDENCE_OUTPUT", "artifacts/xau-v47-opr-context-v76.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V76_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, payload in decision["scenarios"].items():
        print(
            f"V76_COST cost={cost_id} "
            f"satellite={_metric_line(payload['satellite']['metrics'])}"
        )
        for window, row in payload["diagnostic_windows"].items():
            print(
                f"V76_WINDOW cost={cost_id} window={window} "
                f"all={_metric_line(row['all']['metrics'])} coverage={row['coverage']}"
            )
            for state, stats in row["entry_position"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V76_ENTRY_POSITION cost={cost_id} window={window} state={state} "
                        f"{_metric_line(stats['metrics'])}"
                    )
            for state, stats in row["touch_or_cross_close_above"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V76_RETEST cost={cost_id} window={window} state={state} "
                        f"{_metric_line(stats['metrics'])}"
                    )
            for bucket, stats in row["opr_range_to_h1_atr"].items():
                if int(stats["trades"]) > 0:
                    print(
                        f"V76_OPR_ATR cost={cost_id} window={window} bucket={bucket} "
                        f"{_metric_line(stats['metrics'])}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

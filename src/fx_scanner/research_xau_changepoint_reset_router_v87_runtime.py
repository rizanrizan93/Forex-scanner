from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import ensure_utc
from .research_xau_changepoint_reset_router_v87 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v87,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    COST_SCENARIOS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_changepoint_reset_router_v87"

CONTINUOUS = {
    "fetch_start": datetime(2011, 1, 1, tzinfo=UTC),
    "start": datetime(2012, 1, 1, tzinfo=UTC),
    "end": datetime(2026, 9, 20, tzinfo=UTC),
}
ERA_WINDOWS = {
    "2012_2018": (
        datetime(2012, 1, 1, tzinfo=UTC),
        datetime(2019, 1, 1, tzinfo=UTC),
    ),
    "2019_2024": (
        datetime(2019, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
    ),
    "2025_2026YTD": (
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 9, 20, tzinfo=UTC),
    ),
}


def run() -> int:
    bars = _fetch(CONTINUOUS)
    decision = evaluate_v87(
        bars,
        evaluation_start=CONTINUOUS["start"],
        evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,
        cost_scenarios=COST_SCENARIOS,
        era_windows=ERA_WINDOWS,
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
            "V87_EVIDENCE_OUTPUT",
            "artifacts/xau-changepoint-reset-router-v87.json",
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
        )
        + "\n"
    )

    print(
        f"V87_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cp in decision["change_points"]:
        print(
            "V87_CHANGE_POINT "
            f"confirm={cp['confirm_at']} effective={cp['effective_at']} "
            f"shock_features={cp['shock_feature_count']}"
        )
    for cost_id, payload in decision["scenario_results"].items():
        full = payload["full_period"]
        print(
            f"V87_FULL cost={cost_id} "
            f"core={_metric_line(full['core_d1']['metrics'])} "
            f"v47_sat={_metric_line(full['frozen_v47_satellite']['metrics'])} "
            f"reset_sat={_metric_line(full['reset_satellite']['metrics'])}"
        )
        for era_id, era in payload["eras"].items():
            print(
                f"V87_ERA era={era_id} cost={cost_id} "
                f"core={_metric_line(era['core_d1']['metrics'])} "
                f"v47={_metric_line(era['frozen_v47_satellite']['metrics'])} "
                f"reset={_metric_line(era['reset_satellite']['metrics'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

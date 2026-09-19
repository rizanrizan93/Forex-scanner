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
from .research_xau_transition_regime_router_v41 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v41,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_transition_regime_router_v41"


def run() -> int:
    era_id = os.environ.get("V41_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V41_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)

    decision = evaluate_v41(
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

    path = Path(
        os.getenv(
            "V41_EVIDENCE_OUTPUT",
            f"artifacts/xau-transition-regime-router-v41-{era_id}.json",
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
        f"V41_RESULT era={era_id} rows={len(bars)} "
        f"episodes={decision['transition_episodes']} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for cost_id, scenario in decision["scenario_results"].items():
        for portfolio_id, payload in scenario["portfolios"].items():
            print(
                f"V41_PORTFOLIO era={era_id} cost={cost_id} id={portfolio_id} "
                f"{_metric_line(payload['metrics'])} "
                f"tpd={payload['trades_per_day']} "
                f"loss_streak={payload['max_losing_streak']}"
            )
        if cost_id == "V24_STRESS_4675":
            for route, payload in scenario["routed_m15"].items():
                print(
                    f"V41_ROUTE era={era_id} id={route} "
                    f"{_metric_line(payload['metrics'])} "
                    f"tpd={payload['trades_per_day']} "
                    f"loss_streak={payload['max_losing_streak']}"
                )
            for key, payload in scenario["diagnostics"]["family_x_post_flip_phase"].items():
                print(
                    f"V41_DIAG_PHASE era={era_id} bucket={key} "
                    f"{_metric_line(payload['metrics'])} "
                    f"tpd={payload['trades_per_day']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

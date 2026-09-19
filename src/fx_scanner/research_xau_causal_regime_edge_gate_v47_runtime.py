from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_causal_regime_edge_gate_v47 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v47,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    ERAS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_causal_regime_edge_gate_v47"


def run() -> int:
    era_id = os.environ.get("V47_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V47_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v47(
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

    path = Path(os.getenv("V47_EVIDENCE_OUTPUT", f"artifacts/xau-causal-regime-edge-gate-v47-{era_id}.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    print(
        f"V47_RESULT era={era_id} rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    stress = decision["scenario_results"]["V24_STRESS_4675"]
    print(
        f"V47_CORE era={era_id} "
        f"{_metric_line(stress['core_d1_classic']['metrics'])}"
    )
    for route, payload in stress["routes"].items():
        for state in ("ungated", "gated"):
            row = payload[state]
            print(
                f"V47_ROUTE era={era_id} id={route} state={state} "
                f"{_metric_line(row['metrics'])} tpd={row['trades_per_day']} "
                f"loss_streak={row['max_losing_streak']}"
            )
        for family, gate in payload["gates"].items():
            print(
                f"V47_GATE era={era_id} route={route} family={family} "
                f"candidate={gate['candidate_trades']} kept={gate['kept_trades']} "
                f"activation={gate['activation_fraction']} first={gate['first_active_at']}"
            )
        p = stress["portfolios"][route]["gated_d1_plus_route"]
        print(
            f"V47_PORTFOLIO era={era_id} id={route} "
            f"{_metric_line(p['metrics'])} tpd={p['trades_per_day']} "
            f"loss_streak={p['max_losing_streak']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

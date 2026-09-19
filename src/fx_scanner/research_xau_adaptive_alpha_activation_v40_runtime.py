from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dukascopy_python import instruments

from .research_xau_adaptive_alpha_activation_v40 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v40,
)
from .research_xau_crossasset_leadlag_v39_runtime import _fetch_h1
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
WORKER_NAME = "dukascopy_xau_adaptive_alpha_activation_v40"


def run() -> int:
    era_id = os.environ.get("V40_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V40_ERA_INVALID:{era_id}")
    era = ERAS[era_id]

    xau = _fetch(era)
    xag = _fetch_h1(
        era,
        instrument=instruments.INSTRUMENT_FX_METALS_XAG_USD,
        symbol="XAGUSD",
    )
    eur = _fetch_h1(
        era,
        instrument=instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
        symbol="EURUSD",
    )

    decision = evaluate_v40(
        xau,
        xag_h1=xag,
        eur_h1=eur,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
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
        "data_source": {
            "xau": "Dukascopy Bank BID M15",
            "xag": "Dukascopy Bank BID H1",
            "eurusd": "Dukascopy Bank BID H1",
        },
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
            "V40_EVIDENCE_OUTPUT",
            f"artifacts/xau-adaptive-alpha-activation-v40-{era_id}.json",
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
        f"V40_RESULT era={era_id} xau={len(xau)} xag_h1={len(xag)} "
        f"eur_h1={len(eur)} artifact={path} policy=SHADOW_ONLY "
        "execution_influence=0 promotion_eligible=0"
    )
    for cost_id, scenario in decision["scenario_results"].items():
        core = scenario["core_d1_classic"]
        static = scenario["always_on_d1_plus_l12_l20"]
        adaptive = scenario["adaptive_d1_plus_satellites"]
        print(
            f"V40_PORTFOLIO era={era_id} cost={cost_id} id=CORE "
            f"{_metric_line(core['metrics'])} tpd={core['trades_per_day']}"
        )
        print(
            f"V40_PORTFOLIO era={era_id} cost={cost_id} id=STATIC_L12_L20 "
            f"{_metric_line(static['metrics'])} tpd={static['trades_per_day']}"
        )
        print(
            f"V40_PORTFOLIO era={era_id} cost={cost_id} id=ADAPTIVE "
            f"{_metric_line(adaptive['metrics'])} tpd={adaptive['trades_per_day']} "
            f"loss_streak={adaptive['max_losing_streak']}"
        )
        if cost_id == "V24_STRESS_4675":
            for family, gate in scenario["gates"].items():
                metrics = scenario["adaptive_satellite_family_metrics"][family]
                print(
                    f"V40_GATE era={era_id} family={family} "
                    f"kept={gate['kept_trades']} suppressed={gate['suppressed_trades']} "
                    f"activation_fraction={gate['activation_fraction']} "
                    f"era_n={metrics['trades']} "
                    f"{_metric_line(metrics['metrics'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

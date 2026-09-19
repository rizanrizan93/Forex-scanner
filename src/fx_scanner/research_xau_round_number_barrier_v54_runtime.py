from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_hierarchical_regime_router_v35_runtime import ERAS, _fetch
from .research_xau_round_number_barrier_v54 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_v54,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_round_number_barrier_v54"


def _fmt(summary):
    if not summary or int(summary.get("events", 0)) <= 0:
        return "events=0"
    h16 = summary.get("h16", {})
    vol = summary.get("volatility_shift_16", {})
    return (
        f"events={summary['events']} "
        f"h16_mean={h16.get('directional_mean_atr')} "
        f"h16_pos={h16.get('directional_positive_fraction')} "
        f"h16_mfe={h16.get('mfe_mean_atr')} "
        f"h16_mae={h16.get('mae_mean_atr')} "
        f"vol_ratio={vol.get('mean_post_pre_abs_move_ratio')} "
        f"vol_gt_pre={vol.get('fraction_post_gt_pre')}"
    )


def run() -> int:
    era_id = os.environ.get("V54_ERA", "").strip()
    if era_id not in ERAS:
        raise SystemExit(f"V54_ERA_INVALID:{era_id}")
    era = ERAS[era_id]
    bars = _fetch(era)
    decision = evaluate_v54(
        bars,
        era_id=era_id,
        era_start=era["start"],
        era_end=era["end"],
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
            f"{WORKER_NAME}_{era_id}",
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(
        os.getenv(
            "V54_EVIDENCE_OUTPUT",
            f"artifacts/xau-round-number-barrier-v54-{era_id}.json",
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
        f"V54_RESULT era={era_id} rows={len(bars)} "
        f"events={decision['event_count']} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for key, summary in decision["by_barrier_class_and_event"].items():
        print(f"V54_EVENT era={era_id} key={key} {_fmt(summary)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

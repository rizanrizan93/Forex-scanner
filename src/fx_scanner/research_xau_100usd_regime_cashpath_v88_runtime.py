from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .research_xau_100usd_regime_cashpath_v88 import (
    ARTIFACT_CONTRACT,
    COST_SCENARIO_ID,
    RESEARCH_VERSION,
    evaluate_v88,
)
from .research_xau_hierarchical_regime_router_v35_runtime import (
    BROKER_SPEC,
    COST_SCENARIOS,
    LEVERAGE_TIERS,
    _fetch,
    _metric_line,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "dukascopy_xau_100usd_regime_cashpath_v88"

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
    decision = evaluate_v88(
        bars,
        evaluation_start=CONTINUOUS["start"],
        evaluation_end=CONTINUOUS["end"],
        pip_size=0.01,
        costs=COST_SCENARIOS[COST_SCENARIO_ID],
        broker_spec=BROKER_SPEC,
        leverage_tiers=LEVERAGE_TIERS,
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
            "V88_EVIDENCE_OUTPUT",
            "artifacts/xau-100usd-regime-cashpath-v88.json",
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
        f"V88_RESULT rows={len(bars)} artifact={path} "
        "policy=SHADOW_ONLY execution_influence=0 promotion_eligible=0"
    )
    for portfolio_id, payload in decision["portfolio_results"].items():
        cash = payload["continuous_cash_path"]
        metric = payload["signal_level_full"]["metrics"]
        print(
            f"V88_PORTFOLIO id={portfolio_id} "
            f"{_metric_line(metric)} "
            f"ending={cash['ending_balance_usd']} "
            f"return_pct={cash['return_pct']} "
            f"min_balance={cash['minimum_realized_balance_usd']} "
            f"max_dd_pct={cash['max_realized_drawdown_pct']} "
            f"opened={cash['opened_trades']} "
            f"margin_skips={cash['margin_skips']} "
            f"guard_skips={cash['planned_stop_guard_skips']} "
            f"ruin={cash['ruin']} hit1000={cash['hit_1000']}"
        )
        for label, cp in cash["checkpoints"].items():
            print(
                f"V88_CHECKPOINT id={portfolio_id} label={label} "
                f"at={cp['at']} balance={cp['realized_balance_usd']} "
                f"active={cp['active_positions']} margin={cp['margin_used_usd']}"
            )
        for era_id, era in payload["signal_level_by_era"].items():
            print(
                f"V88_ERA id={portfolio_id} era={era_id} "
                f"{_metric_line(era['metrics'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

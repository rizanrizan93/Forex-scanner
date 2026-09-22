from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_expected_move_envelope_v170 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_expected_move_v170,
)
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_expected_move_envelope_v170"
HISTORY_TARGET = 100_000


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_EXPECTED_MOVE_V170_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_EXPECTED_MOVE_V170_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_EXPECTED_MOVE_V170_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=HISTORY_TARGET, as_of=now)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    evaluation = evaluate_expected_move_v170(bars)
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target_bars": HISTORY_TARGET,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "evaluation": evaluation,
    }

    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    path = Path(
        os.getenv(
            "V170_OUTPUT",
            "artifacts/xau-expected-move-envelope-v170.json",
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

    validation = evaluation["validation"]
    current = evaluation.get("current_envelope")
    print(
        "V170_RESULT "
        f"bars={len(bars)} scored={validation['scored_points']} "
        f"mean_abs_coverage_error={validation['mean_absolute_coverage_error']} "
        f"current_as_of={None if current is None else current['as_of']} "
        f"artifact={path} execution_influence=0"
    )
    if current is not None:
        print(
            "V170_CURRENT "
            + json.dumps(current, sort_keys=True, default=str)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

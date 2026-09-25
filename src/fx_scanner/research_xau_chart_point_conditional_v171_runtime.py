from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .research_xau_chart_point_conditional_v171 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v171,
)
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_chart_point_conditional_v171"
REQUEST_COUNT = 5000


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V171_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V171_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_V171_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        rows = tuple(
            feed.historical_bars(
                SYMBOL,
                "D1",
                from_time=now - timedelta(days=6500),
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    closed = tuple(
        row
        for row in sorted(rows, key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(days=1) <= now
    )
    if len(closed) < 300:
        raise SystemExit(f"XAU_V171_D1_HISTORY_INSUFFICIENT:{len(closed)}")

    evaluation = evaluate_v171(closed)
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
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
            "V171_OUTPUT",
            "artifacts/xau-chart-point-conditional-v171.json",
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

    for scope in ("full", "development", "holdout"):
        for label, row in evaluation[scope].items():
            print(
                "V171_SCOPE "
                + json.dumps(
                    {
                        "scope": scope.upper(),
                        "case": label,
                        "extreme_n": row["extreme_momentum"]["n"],
                        "extreme_revisit_5d": row["extreme_momentum"]["revisit_5d_rate"],
                        "baseline_n": row["same_sign_non_extreme_baseline"]["n"],
                        "baseline_revisit_5d": row["same_sign_non_extreme_baseline"]["revisit_5d_rate"],
                        "lift_5d": row["primary_5d_revisit_lift"],
                    },
                    sort_keys=True,
                )
            )
    print(
        "V171_DECISION "
        + json.dumps(
            {
                "diagnostic_only": True,
                "promotion": False,
                "execution_changed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

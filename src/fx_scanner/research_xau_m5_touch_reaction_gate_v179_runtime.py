from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_h1_origin_hold_break_m5_v178_runtime import (
    M15_SECONDS,
    M15_TARGET,
    M5_SECONDS,
    M5_TARGET,
    _fetch_history,
)
from .research_xau_m5_touch_reaction_gate_v179 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_research,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_m5_touch_reaction_gate_v179"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_M5_TOUCH_REACTION_GATE_V179_OUTPUT",
        "artifacts/xau-m5-touch-reaction-gate-v179.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_M5_TOUCH_REACTION_GATE_V179_OUTPUT_REQUIRED")
    return Path(raw)


def _write_artifact(details: dict[str, Any]) -> str:
    path = _artifact_path()
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
            allow_nan=False,
        )
        + "\n"
    )
    return str(path)


def _heartbeat(details: dict[str, Any], *, healthy: bool) -> None:
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=healthy,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_M5_TOUCH_REACTION_GATE_V179_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_M5_TOUCH_REACTION_GATE_V179_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_M5_TOUCH_REACTION_GATE_V179_SYMBOL_NOT_CONFIGURED")

    observed_at = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        m15_bars, m15_pages = _fetch_history(
            feed,
            timeframe="M15",
            timeframe_seconds=M15_SECONDS,
            target=M15_TARGET,
            as_of=observed_at,
        )
        m5_bars, m5_pages = _fetch_history(
            feed,
            timeframe="M5",
            timeframe_seconds=M5_SECONDS,
            target=M5_TARGET,
            as_of=observed_at,
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    details: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "promotion_authority": False,
        "live_execution_enabled": False,
        "observed_at": observed_at.isoformat(),
        "history": {
            "M15": {
                "target": M15_TARGET,
                "actual_closed_bars": len(m15_bars),
                "pages": m15_pages,
            },
            "M5": {
                "target": M5_TARGET,
                "actual_closed_bars": len(m5_bars),
                "pages": m5_pages,
            },
        },
    }

    if (
        len(m15_bars) < int(M15_TARGET * 0.95)
        or len(m5_bars) < int(M5_TARGET * 0.95)
    ):
        details["decision"] = "DATA_INSUFFICIENT"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_M5_TOUCH_REACTION_GATE_V179 "
            f"decision=DATA_INSUFFICIENT artifact={artifact}"
        )
        return 0

    details["evaluation"] = evaluate_research(m15_bars, m5_bars)
    details["decision"] = details["evaluation"]["decision"]
    artifact = _write_artifact(details)
    healthy = details["decision"] != "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT"
    _heartbeat(details, healthy=healthy)

    directions = details["evaluation"].get("directions", {})
    print(
        "XAU_M5_TOUCH_REACTION_GATE_V179 "
        f"episodes={details['evaluation'].get('episodes')} "
        f"decision={details['decision']} "
        f"long_precision="
        f"{directions.get('LONG', {}).get('untouched_holdout', {}).get('precision_hold')} "
        f"short_precision="
        f"{directions.get('SHORT', {}).get('untouched_holdout', {}).get('precision_hold')} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

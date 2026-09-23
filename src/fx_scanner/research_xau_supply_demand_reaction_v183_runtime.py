from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_m15_dual_strategy_runtime import _fetch_history, _history_target
from .research_xau_supply_demand_reaction_v183 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_supply_demand_research,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_supply_demand_reaction_v183"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_SUPPLY_DEMAND_REACTION_V183_OUTPUT",
        "artifacts/xau-supply-demand-reaction-v183.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_SUPPLY_DEMAND_REACTION_V183_OUTPUT_REQUIRED")
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
        raise SystemExit("XAU_SUPPLY_DEMAND_REACTION_V183_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_SUPPLY_DEMAND_REACTION_V183_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_SUPPLY_DEMAND_REACTION_V183_SYMBOL_NOT_CONFIGURED")

    target = _history_target()
    observed_at = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=target, as_of=observed_at)
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
        "history_target_bars": target,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
    }

    if len(bars) < 20_000:
        details["decision"] = "DATA_INSUFFICIENT"
        details["reason"] = f"M15_HISTORY_BELOW_MINIMUM:{len(bars)}<20000"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_SUPPLY_DEMAND_REACTION_V183 "
            f"bars={len(bars)} decision=DATA_INSUFFICIENT "
            f"artifact={artifact} execution_influence=0"
        )
        return 0

    details["evaluation"] = evaluate_supply_demand_research(bars)
    details["decision"] = details["evaluation"]["decision"]
    artifact = _write_artifact(details)
    healthy = details["decision"] != "DATA_INSUFFICIENT_FOR_CAUSAL_HOLDOUT"
    _heartbeat(details, healthy=healthy)

    holdout = dict(details["evaluation"].get("holdout_overall") or {})
    print(
        "XAU_SUPPLY_DEMAND_REACTION_V183 "
        f"bars={len(bars)} zones={details['evaluation'].get('zones')} "
        f"episodes={details['evaluation'].get('episodes')} "
        f"decision={details['decision']} "
        f"holdout_n={holdout.get('n')} "
        f"holdout_precision={holdout.get('precision_hold')} "
        f"candidates={len(details['evaluation'].get('candidate_80_precision_subsets') or [])} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

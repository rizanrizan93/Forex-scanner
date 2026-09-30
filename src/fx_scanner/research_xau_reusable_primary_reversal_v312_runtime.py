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
from .research_xau_reusable_primary_reversal_v312 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_reusable_primary_reversal_cycles,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_reusable_primary_reversal_v312"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_REUSABLE_PRIMARY_REVERSAL_V312_OUTPUT",
        "artifacts/xau-reusable-primary-reversal-v312.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_REUSABLE_PRIMARY_REVERSAL_V312_OUTPUT_REQUIRED")
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
        + "\n",
        encoding="utf-8",
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
        raise SystemExit("XAU_REUSABLE_PRIMARY_REVERSAL_V312_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_REUSABLE_PRIMARY_REVERSAL_V312_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_REUSABLE_PRIMARY_REVERSAL_V312_SYMBOL_NOT_CONFIGURED")

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
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "observed_at": observed_at.isoformat(),
        "history_target_bars": target,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }

    if len(bars) < 20_000:
        details["decision"] = "DATA_INSUFFICIENT"
        details["reason"] = f"M15_HISTORY_BELOW_MINIMUM:{len(bars)}<20000"
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_REUSABLE_PRIMARY_REVERSAL_V312 "
            f"bars={len(bars)} decision=DATA_INSUFFICIENT artifact={artifact}"
        )
        return 0

    evaluation = evaluate_reusable_primary_reversal_cycles(bars)
    details["evaluation"] = evaluation
    gate = dict(evaluation.get("pre_registered_research_gate") or {})
    details["decision"] = (
        "RESEARCH_GATE_PASSED_DEEPER_EXACT_ENTRY_ONLY"
        if bool(gate.get("passed"))
        else "RESEARCH_GATE_NOT_PASSED"
    )
    artifact = _write_artifact(details)
    _heartbeat(details, healthy=True)

    fresh = dict(evaluation.get("fresh_only") or {})
    reusable = dict(evaluation.get("fresh_plus_v200_reusable") or {})
    comparison = dict(evaluation.get("comparison") or {})
    print(
        "XAU_REUSABLE_PRIMARY_REVERSAL_V312 "
        f"bars={len(bars)} "
        f"fresh_coverage={fresh.get('coverage_rate')} "
        f"reuse_coverage={reusable.get('coverage_rate')} "
        f"uplift_pp={comparison.get('coverage_uplift_percentage_points')} "
        f"reuse_second_hold={reusable.get('second_hold_rate_all_selected')} "
        f"gate={gate.get('passed')} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

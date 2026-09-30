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
from .research_xau_structural_cycle_v311 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_structural_cycles,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_structural_cycle_v311"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_STRUCTURAL_CYCLE_V311_OUTPUT",
        "artifacts/xau-structural-cycle-v311.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_STRUCTURAL_CYCLE_V311_OUTPUT_REQUIRED")
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
        raise SystemExit("XAU_STRUCTURAL_CYCLE_V311_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_STRUCTURAL_CYCLE_V311_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_STRUCTURAL_CYCLE_V311_SYMBOL_NOT_CONFIGURED")

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
            "XAU_STRUCTURAL_CYCLE_V311 "
            f"bars={len(bars)} decision=DATA_INSUFFICIENT artifact={artifact}"
        )
        return 0

    evaluation = evaluate_structural_cycles(bars)
    details["evaluation"] = evaluation
    details["decision"] = "RESEARCH_EVIDENCE_READY"
    artifact = _write_artifact(details)
    _heartbeat(details, healthy=True)

    summary = dict(evaluation.get("summary") or {})
    print(
        "XAU_STRUCTURAL_CYCLE_V311 "
        f"bars={len(bars)} first={summary.get('first_reaction_milestones')} "
        f"clean={summary.get('clean_opposite_candidates')} "
        f"second_hold={summary.get('second_hold')} "
        f"clean_hold_rate={summary.get('second_hold_rate_all_clean')} "
        f"first_completion={summary.get('structural_cycle_completion_rate_of_first_reactions')} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

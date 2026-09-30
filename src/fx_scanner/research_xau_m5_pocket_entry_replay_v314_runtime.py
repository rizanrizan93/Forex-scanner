from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_h1_m5_reconfirmation_v313_runtime import (
    M15_TARGET,
    M5_TARGET,
    _fetch_timeframe,
)
from .research_xau_m5_pocket_entry_replay_v314 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_m5_pocket_entry_replay,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_m5_pocket_entry_replay_v314"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_M5_POCKET_ENTRY_REPLAY_V314_OUTPUT",
        "artifacts/xau-m5-pocket-entry-replay-v314.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_M5_POCKET_ENTRY_REPLAY_V314_OUTPUT_REQUIRED")
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
        raise SystemExit("XAU_M5_POCKET_ENTRY_REPLAY_V314_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_M5_POCKET_ENTRY_REPLAY_V314_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_M5_POCKET_ENTRY_REPLAY_V314_SYMBOL_NOT_CONFIGURED")

    observed_at = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        m15_bars, m15_pages = _fetch_timeframe(
            feed,
            timeframe="M15",
            timeframe_seconds=15 * 60,
            target=M15_TARGET,
            as_of=observed_at,
        )
        m5_bars, m5_pages = _fetch_timeframe(
            feed,
            timeframe="M5",
            timeframe_seconds=5 * 60,
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
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "observed_at": observed_at.isoformat(),
        "m15_target": M15_TARGET,
        "m15_actual_closed": len(m15_bars),
        "m15_pages": m15_pages,
        "m5_target": M5_TARGET,
        "m5_actual_closed": len(m5_bars),
        "m5_pages": m5_pages,
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }

    if len(m15_bars) < 20_000 or len(m5_bars) < 30_000:
        details["decision"] = "DATA_INSUFFICIENT"
        details["reason"] = (
            f"M15={len(m15_bars)}<20000_OR_M5={len(m5_bars)}<30000"
        )
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_M5_POCKET_ENTRY_REPLAY_V314 "
            f"m15={len(m15_bars)} m5={len(m5_bars)} "
            f"decision=DATA_INSUFFICIENT artifact={artifact}"
        )
        return 0

    evaluation = evaluate_m5_pocket_entry_replay(m15_bars, m5_bars)
    details["evaluation"] = evaluation
    details["decision"] = evaluation["decision"]
    artifact = _write_artifact(details)
    _heartbeat(details, healthy=True)

    selected = dict(evaluation.get("selected_holdout") or {})
    summary = dict(selected.get("summary") or {})
    gate = dict(evaluation.get("holdout_gate") or {})
    print(
        "XAU_M5_POCKET_ENTRY_REPLAY_V314 "
        f"m15={len(m15_bars)} m5={len(m5_bars)} "
        f"confirmed={evaluation.get('confirmed_v313_opportunities')} "
        f"selected={evaluation.get('selection_contract',{}).get('selected_key')} "
        f"fills={summary.get('fills')} "
        f"fill_rate={summary.get('fill_rate')} "
        f"tp_rate={summary.get('tp_rate')} "
        f"pf={summary.get('profit_factor')} "
        f"avg_r={summary.get('avg_net_r')} "
        f"precision={summary.get('precision_5_and_tp_rate')} "
        f"gate={gate.get('passed')} artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

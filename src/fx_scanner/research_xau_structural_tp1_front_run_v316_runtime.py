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
from .research_xau_structural_tp1_front_run_v316 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_structural_tp1_front_run,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_structural_tp1_front_run_v316"


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_STRUCTURAL_TP1_V316_OUTPUT",
        "artifacts/xau-structural-tp1-front-run-v316.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_STRUCTURAL_TP1_V316_OUTPUT_REQUIRED")
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


def _compact(evaluation: dict[str, Any]) -> dict[str, Any]:
    selected = dict(evaluation.get("selected_holdout") or {})
    return {
        "research_version": evaluation.get("research_version"),
        "confirmed_opportunities": evaluation.get("confirmed_opportunities"),
        "development_opportunities": evaluation.get("development_opportunities"),
        "holdout_opportunities": evaluation.get("holdout_opportunities"),
        "selected_mode": evaluation.get("selected_mode"),
        "selected_holdout": {
            "mode": selected.get("mode"),
            "summary": selected.get("summary"),
        } if selected else None,
        "holdout_gate": evaluation.get("holdout_gate"),
        "decision": evaluation.get("decision"),
        "full_evidence_location": "GITHUB_ACTIONS_ARTIFACT",
        "execution_influence": False,
        "execution_authority": False,
    }


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
        raise SystemExit("XAU_STRUCTURAL_TP1_V316_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_STRUCTURAL_TP1_V316_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_STRUCTURAL_TP1_V316_SYMBOL_NOT_CONFIGURED")

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

    base = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "observed_at": observed_at.isoformat(),
        "m15_actual_closed": len(m15_bars),
        "m15_pages": m15_pages,
        "m5_actual_closed": len(m5_bars),
        "m5_pages": m5_pages,
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }
    if len(m15_bars) < 20_000 or len(m5_bars) < 30_000:
        details = {
            **base,
            "decision": "DATA_INSUFFICIENT",
            "reason": f"M15={len(m15_bars)}_M5={len(m5_bars)}",
        }
        artifact = _write_artifact(details)
        _heartbeat({**details, "artifact": artifact}, healthy=False)
        return 0

    evaluation = evaluate_structural_tp1_front_run(m15_bars, m5_bars)
    artifact = _write_artifact({**base, "evaluation": evaluation})
    compact = _compact(evaluation)
    heartbeat = {**base, "evaluation": compact, "artifact": artifact}
    _heartbeat(heartbeat, healthy=True)

    selected = dict(evaluation.get("selected_holdout") or {})
    summary = dict(selected.get("summary") or {})
    print(
        "XAU_STRUCTURAL_TP1_FRONT_RUN_V316 "
        f"selected={evaluation.get('selected_mode')} "
        f"fills={summary.get('fills')} tp1={summary.get('tp1_hit_rate')} "
        f"wilson={summary.get('tp1_wilson_lower_95')} "
        f"precision={summary.get('precision_5_and_tp1_rate')} "
        f"pf={summary.get('profit_factor')} avg_r={summary.get('avg_net_r')} "
        f"gate={dict(evaluation.get('holdout_gate') or {}).get('passed')} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

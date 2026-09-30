from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_h1_m5_reconfirmation_v313 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_h1_m5_reconfirmation,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_h1_m5_reconfirmation_v313"
M15_TARGET = 50_000
M5_TARGET = 100_000
PAGE_BARS = 5_000
MAX_PAGES = 20


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_H1_M5_RECONFIRMATION_V313_OUTPUT",
        "artifacts/xau-h1-m5-reconfirmation-v313.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_H1_M5_RECONFIRMATION_V313_OUTPUT_REQUIRED")
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


def _fetch_timeframe(
    feed,
    *,
    timeframe: str,
    timeframe_seconds: int,
    target: int,
    as_of: datetime,
) -> tuple[tuple[Any, ...], list[dict[str, Any]]]:
    merged: dict[datetime, Any] = {}
    cursor = as_of
    pages: list[dict[str, Any]] = []
    previous_earliest: datetime | None = None

    for page in range(1, MAX_PAGES + 1):
        remaining = target - len(merged)
        if remaining <= 0:
            break
        request_count = min(PAGE_BARS, remaining)
        start = cursor - timedelta(seconds=request_count * timeframe_seconds * 3)
        fetched = tuple(
            feed.historical_bars(
                SYMBOL,
                timeframe,
                from_time=start,
                to_time=cursor,
                count=request_count,
            )
        )
        if not fetched:
            break
        for row in fetched:
            merged[ensure_utc(row.timestamp)] = row
        earliest = min(ensure_utc(row.timestamp) for row in fetched)
        latest = max(ensure_utc(row.timestamp) for row in fetched)
        pages.append(
            {
                "page": page,
                "requested": request_count,
                "received": len(fetched),
                "merged_total": len(merged),
                "earliest": earliest.isoformat(),
                "latest": latest.isoformat(),
            }
        )
        if previous_earliest is not None and earliest >= previous_earliest:
            break
        previous_earliest = earliest
        cursor = earliest - timedelta(seconds=1)

    rows = tuple(sorted(merged.values(), key=lambda row: ensure_utc(row.timestamp)))
    closed = tuple(
        row
        for row in rows
        if ensure_utc(row.timestamp) + timedelta(seconds=timeframe_seconds) <= as_of
    )
    if len(closed) > target:
        closed = closed[-target:]
    return closed, pages


# Local import after helper declaration keeps the module dependency explicit.
from .models import ensure_utc  # noqa: E402


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_H1_M5_RECONFIRMATION_V313_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_H1_M5_RECONFIRMATION_V313_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_H1_M5_RECONFIRMATION_V313_SYMBOL_NOT_CONFIGURED")

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
            "XAU_H1_M5_RECONFIRMATION_V313 "
            f"m15={len(m15_bars)} m5={len(m5_bars)} "
            f"decision=DATA_INSUFFICIENT artifact={artifact}"
        )
        return 0

    evaluation = evaluate_h1_m5_reconfirmation(m15_bars, m5_bars)
    details["evaluation"] = evaluation
    details["decision"] = evaluation["decision"]
    artifact = _write_artifact(details)
    _heartbeat(details, healthy=True)

    primary = (
        evaluation.get("policies", {})
        .get("STRUCTURAL_PRIOR_HOLD_H1_MICRO_REQUIRED", {})
        .get("holdout", {})
    )
    gate = dict(evaluation.get("primary_holdout_gate") or {})
    print(
        "XAU_H1_M5_RECONFIRMATION_V313 "
        f"m15={len(m15_bars)} m5={len(m5_bars)} "
        f"selected={primary.get('selected_candidates')} "
        f"confirmed={primary.get('m5_confirmed')} "
        f"confirm_rate={primary.get('confirmation_rate_of_selected')} "
        f"post_hold={primary.get('post_confirm_hold_rate')} "
        f"wilson={primary.get('post_confirm_wilson_lower_95')} "
        f"uplift_pp={primary.get('uplift_pp_vs_touch_baseline')} "
        f"gate={gate.get('passed')} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

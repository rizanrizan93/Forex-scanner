from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_h1_origin_hold_break_m5_v178 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    evaluate_research,
)
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_xau_h1_origin_hold_break_m5_v178"

M15_TARGET = 100_000
M5_TARGET = 300_000
PAGE_BARS = 5_000
M15_SECONDS = 15 * 60
M5_SECONDS = 5 * 60


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_OUTPUT",
        "artifacts/xau-h1-origin-hold-break-m5-v178.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_OUTPUT_REQUIRED")
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


def _fetch_history(
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
    max_pages = (int(target) + PAGE_BARS - 1) // PAGE_BARS

    for page in range(1, max_pages + 1):
        remaining = int(target) - len(merged)
        if remaining <= 0:
            break
        request_count = min(PAGE_BARS, remaining)
        start = cursor - timedelta(
            seconds=request_count * int(timeframe_seconds) * 3
        )
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
            merged[row.timestamp] = row
        earliest = min(row.timestamp for row in fetched)
        latest = max(row.timestamp for row in fetched)
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

    rows = tuple(sorted(merged.values(), key=lambda row: row.timestamp))
    closed = tuple(
        row
        for row in rows
        if row.timestamp.astimezone(UTC)
        + timedelta(seconds=timeframe_seconds)
        <= as_of
    )
    if len(closed) > target:
        closed = closed[-target:]
    return closed, pages


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)

    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_H1_ORIGIN_HOLD_BREAK_M5_V178_SYMBOL_NOT_CONFIGURED")

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

    minimum_m15 = int(M15_TARGET * 0.95)
    minimum_m5 = int(M5_TARGET * 0.95)
    if len(m15_bars) < minimum_m15 or len(m5_bars) < minimum_m5:
        details["decision"] = "DATA_INSUFFICIENT"
        details["reason"] = (
            f"HISTORY_COVERAGE:"
            f"M15={len(m15_bars)}/{minimum_m15};"
            f"M5={len(m5_bars)}/{minimum_m5}"
        )
        artifact = _write_artifact(details)
        _heartbeat(details, healthy=False)
        print(
            "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178 "
            f"decision=DATA_INSUFFICIENT artifact={artifact} "
            "execution_influence=0"
        )
        return 0

    details["evaluation"] = evaluate_research(m15_bars, m5_bars)
    details["decision"] = details["evaluation"]["decision"]
    artifact = _write_artifact(details)
    healthy = details["decision"] != "DATA_INSUFFICIENT_FOR_CAUSAL_SPLIT"
    _heartbeat(details, healthy=healthy)

    directions = details["evaluation"].get("directions", {})
    print(
        "XAU_H1_ORIGIN_HOLD_BREAK_M5_V178 "
        f"m15={len(m15_bars)} m5={len(m5_bars)} "
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

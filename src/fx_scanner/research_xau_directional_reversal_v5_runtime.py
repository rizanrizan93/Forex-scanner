from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_directional_reversal_v5 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_directional_reversal_v5,
)
from .research_xau_m15_continuation_tournament import PIP_SIZE
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import (
    MIN_HISTORY_BARS,
    _costs,
    _validation_cfg,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_directional_reversal_v5"
HISTORY_BARS = 200_000
PAGE_BARS = 5_000
MAX_PAGES = 50
M15_SECONDS = 15 * 60


def _fetch_history_v5(feed, *, target: int, as_of: datetime):
    merged = {}
    cursor = as_of
    pages: list[dict[str, Any]] = []
    previous_earliest = None
    for page in range(1, MAX_PAGES + 1):
        remaining = target - len(merged)
        if remaining <= 0:
            break
        request_count = min(PAGE_BARS, remaining)
        start = cursor - timedelta(seconds=request_count * M15_SECONDS * 3)
        fetched = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
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
        if row.timestamp.astimezone(UTC) + timedelta(seconds=M15_SECONDS) <= as_of
    )
    if len(closed) > target:
        closed = closed[-target:]
    return closed, pages


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_DIRECTIONAL_REVERSAL_V5_EVIDENCE_OUTPUT",
        "artifacts/xau-directional-reversal-v5.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_DIRECTIONAL_REVERSAL_V5_EVIDENCE_OUTPUT_REQUIRED")
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
        raise SystemExit("XAU_DIRECTIONAL_REVERSAL_V5_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_DIRECTIONAL_REVERSAL_V5_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_DIRECTIONAL_REVERSAL_V5_SYMBOL_NOT_CONFIGURED")

    as_of = datetime.now(tz=UTC)
    validation_cfg = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history_v5(feed, target=HISTORY_BARS, as_of=as_of)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=PIP_SIZE) if bars else {
        "available": False,
        "coverage": 0.0,
        "median_pips": None,
        "minimum_pips": None,
        "maximum_pips": None,
        "provenance": "CTRADER_CURRENT_QUOTE_PROXY_ATTACHED_TO_HISTORICAL_BARS",
    }
    details: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": as_of.isoformat(),
        "history_target_bars": HISTORY_BARS,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "spread_proxy": spread,
        "pip_size": PIP_SIZE,
        "hypothesis": (
            "V4 development diagnostics suggested direction-specific US reversal edges. "
            "V5 freezes LONG and SHORT filters/targets separately and tests them on a "
            "materially longer M15 sample before any holdout access."
        ),
    }

    if len(bars) != HISTORY_BARS:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": f"M15_HISTORY_TARGET_NOT_MET:{len(bars)}!={HISTORY_BARS}",
            "promotion_eligible": False,
        }
        _heartbeat(details, healthy=False)
        artifact = _write_artifact(details)
        print(f"CTRADER_XAU_DIRECTIONAL_REVERSAL_V5 stage=DATA_INSUFFICIENT artifact={artifact}")
        return 0
    if not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": "CTRADER_SPREAD_PROXY_UNAVAILABLE",
            "promotion_eligible": False,
        }
        _heartbeat(details, healthy=False)
        artifact = _write_artifact(details)
        print(f"CTRADER_XAU_DIRECTIONAL_REVERSAL_V5 stage=DATA_INSUFFICIENT artifact={artifact}")
        return 0

    base_costs, stressed_costs = _costs(validation_cfg, float(spread["median_pips"]))
    details["costs"] = {
        "base": {
            "spread_proxy_pips": base_costs.spread_pips,
            "slippage_pips": base_costs.slippage_pips,
            "commission_pips_round_trip": base_costs.commission_pips_round_trip,
            "swap_pips_per_day": base_costs.swap_pips_per_day,
        },
        "stress": {
            "spread_multiplier": stressed_costs.spread_multiplier,
            "slippage_multiplier": stressed_costs.slippage_multiplier,
        },
    }
    details["decision"] = evaluate_directional_reversal_v5(
        bars,
        costs=base_costs,
        stressed_costs=stressed_costs,
        validation_cfg=validation_cfg,
    )
    _heartbeat(details, healthy=True)
    artifact = _write_artifact(details)
    decision = details["decision"]
    print(
        "CTRADER_XAU_DIRECTIONAL_REVERSAL_V5 "
        f"bars={len(bars)}/{HISTORY_BARS} spread_pips={float(spread['median_pips']):.4f} "
        f"selected={decision['selected_variant']} "
        f"holdout_opened={int(decision['holdout'] is not None)} "
        f"promotion_eligible={int(bool(decision['promotion_eligible']))} "
        f"artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_m15_dual_strategy import (
    ARTIFACT_CONTRACT,
    PIP_SIZE,
    RESEARCH_VERSION,
    SYMBOL,
    TIMEFRAME_SECONDS,
    M15ResearchCosts,
    evaluate_dual_strategy_research,
    infer_spread_proxy_pips,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_m15_dual_strategy_research"
DEFAULT_HISTORY_BARS = 50_000
MIN_HISTORY_BARS = 5_000
MAX_HISTORY_BARS = 100_000
PAGE_BARS = 5_000
MAX_PAGES = 20


def _validation_cfg() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    value = yaml.safe_load((root / "config" / "validation.yaml").read_text())
    if not isinstance(value, dict):
        raise SystemExit("XAU_M15_RESEARCH_VALIDATION_CONFIG_INVALID")
    return value


def _history_target() -> int:
    raw = os.getenv("CTRADER_XAU_M15_RESEARCH_HISTORY_BARS", str(DEFAULT_HISTORY_BARS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_XAU_M15_RESEARCH_HISTORY_BARS_INVALID") from exc
    if not MIN_HISTORY_BARS <= value <= MAX_HISTORY_BARS:
        raise SystemExit("CTRADER_XAU_M15_RESEARCH_HISTORY_BARS_OUT_OF_RANGE")
    return value


def _artifact_path() -> Path:
    raw = os.getenv(
        "XAU_M15_DUAL_RESEARCH_EVIDENCE_OUTPUT",
        "artifacts/xau-m15-dual-strategy-research.json",
    ).strip()
    if not raw:
        raise SystemExit("XAU_M15_DUAL_RESEARCH_EVIDENCE_OUTPUT_REQUIRED")
    return Path(raw)


def _write_artifact(details: dict[str, Any]) -> str:
    path = _artifact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return str(path)


def _fetch_history(feed, *, target: int, as_of: datetime):
    merged: dict[datetime, Any] = {}
    cursor = as_of
    pages: list[dict[str, Any]] = []
    previous_earliest: datetime | None = None

    for page in range(1, MAX_PAGES + 1):
        remaining = target - len(merged)
        if remaining <= 0:
            break
        request_count = min(PAGE_BARS, remaining)
        # M15 FX/metals trade roughly 5 days/week. A 3x wall-clock range leaves
        # ample room for weekends/holidays without asking cTrader for unbounded history.
        start = cursor - timedelta(seconds=request_count * TIMEFRAME_SECONDS * 3)
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
                "earliest": earliest.isoformat(),
                "latest": latest.isoformat(),
            }
        )
        if previous_earliest is not None and earliest >= previous_earliest:
            break
        previous_earliest = earliest
        cursor = earliest - timedelta(seconds=1)
        if len(fetched) < request_count:
            break

    rows = tuple(sorted(merged.values(), key=lambda row: row.timestamp))
    closed = tuple(
        row
        for row in rows
        if row.timestamp.astimezone(UTC) + timedelta(seconds=TIMEFRAME_SECONDS) <= as_of
    )
    if len(closed) > target:
        closed = closed[-target:]
    return closed, pages


def _costs(validation_cfg: dict[str, Any], spread_proxy_pips: float) -> tuple[M15ResearchCosts, M15ResearchCosts]:
    base_cfg = validation_cfg["costs"]["base"]
    base = M15ResearchCosts(
        spread_pips=float(spread_proxy_pips),
        slippage_pips=float(base_cfg["slippage_pips"]),
        commission_pips_round_trip=float(base_cfg["commission_pips_round_trip"]),
        swap_pips_per_day=float(base_cfg["swap_pips_per_day"]),
    )
    stressed = base.stressed(
        spread_multiplier=float(validation_cfg["costs"]["stress_spread_multiplier"]),
        slippage_multiplier=float(validation_cfg["costs"]["stress_slippage_multiplier"]),
    )
    return base, stressed


def _heartbeat(details: dict[str, Any], *, healthy: bool) -> None:
    try:
        store = SupabaseOperationalStore.from_env()
        store.write_heartbeat(WORKER_NAME, healthy=healthy, lag_seconds=0.0, details=details)
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_M15_RESEARCH_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_M15_RESEARCH_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_M15_RESEARCH_SYMBOL_NOT_CONFIGURED")

    target = _history_target()
    as_of = datetime.now(tz=UTC)
    validation_cfg = _validation_cfg()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=target, as_of=as_of)
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
        "history_target_bars": target,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "spread_proxy": spread,
        "pip_size": PIP_SIZE,
        "cost_provenance_note": (
            "cTrader trendbar history carries the current broker quote spread as a proxy, "
            "not a historical spread series; cost stress is therefore mandatory."
        ),
    }

    if len(bars) < MIN_HISTORY_BARS:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": f"M15_HISTORY_BELOW_MINIMUM:{len(bars)}<{MIN_HISTORY_BARS}",
            "execution_influence": False,
        }
        _heartbeat(details, healthy=False)
        artifact = _write_artifact(details)
        print(
            "CTRADER_XAU_M15_DUAL_RESEARCH "
            f"bars={len(bars)}/{target} stage=DATA_INSUFFICIENT artifact={artifact} execution_influence=0"
        )
        return 0

    if not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": "CTRADER_SPREAD_PROXY_UNAVAILABLE",
            "execution_influence": False,
        }
        _heartbeat(details, healthy=False)
        artifact = _write_artifact(details)
        print(
            "CTRADER_XAU_M15_DUAL_RESEARCH "
            f"bars={len(bars)}/{target} stage=DATA_INSUFFICIENT spread_proxy=0 "
            f"artifact={artifact} execution_influence=0"
        )
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
    details["decision"] = evaluate_dual_strategy_research(
        bars,
        costs=base_costs,
        stressed_costs=stressed_costs,
        validation_cfg=validation_cfg,
    )
    _heartbeat(details, healthy=True)
    artifact = _write_artifact(details)
    stages = ",".join(
        f"{row['strategy_id']}={row['stage']}"
        for row in details["decision"]["strategies"]
    )
    print(
        "CTRADER_XAU_M15_DUAL_RESEARCH "
        f"bars={len(bars)}/{target} spread_pips={float(spread['median_pips']):.4f} "
        f"stages={stages} artifact={artifact} execution_influence=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

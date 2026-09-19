from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .exceptions import CollectorUnavailable
from .models import ensure_utc
from .research_xau_canonical_gate_attribution_v27 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v27,
)
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_canonical_gate_attribution_v27"
HISTORY_TARGET = 50_000
PAGE_BARS = 5_000
MAX_PAGES = 12
TIMEFRAME_SECONDS = 900
CONNECT_BACKOFF = (0.0, 2.0, 5.0)


def _feed(policy):
    last = None
    for delay in CONNECT_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            feed = build_ctrader_research_feed(policy, (SYMBOL,))
            feed.ensure_connected()
            return feed
        except CollectorUnavailable as exc:
            last = exc
            if "connection timeout" not in str(exc).lower():
                raise
    raise CollectorUnavailable("V27_CTRADER_CONNECT_RETRY_EXHAUSTED") from last


def _fetch(feed, as_of: datetime):
    merged = {}
    cursor = as_of
    previous = None
    pages = []
    for page in range(1, MAX_PAGES + 1):
        remaining = HISTORY_TARGET - len(merged)
        if remaining <= 0:
            break
        count = min(PAGE_BARS, remaining)
        try:
            got = tuple(feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=cursor - timedelta(
                    seconds=count * TIMEFRAME_SECONDS * 3
                ),
                to_time=cursor,
                count=count,
            ))
        except CollectorUnavailable as exc:
            pages.append({
                "page": page,
                "received": 0,
                "terminal": f"COLLECTOR_UNAVAILABLE:{exc}",
            })
            break
        if not got:
            break
        for row in got:
            merged[row.timestamp] = row
        earliest = min(x.timestamp for x in got)
        pages.append({
            "page": page,
            "received": len(got),
            "merged": len(merged),
            "earliest": earliest.isoformat(),
            "latest": max(x.timestamp for x in got).isoformat(),
        })
        if previous is not None and earliest >= previous:
            break
        previous = earliest
        cursor = earliest - timedelta(seconds=1)

    rows = tuple(sorted(merged.values(), key=lambda x: x.timestamp))
    closed = tuple(
        x for x in rows
        if ensure_utc(x.timestamp) + timedelta(minutes=15) <= as_of
    )
    return (
        closed[-HISTORY_TARGET:] if len(closed) > HISTORY_TARGET else closed,
        pages,
    )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V27_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V27_REQUIRE_DEMO")

    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V27_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = _feed(policy)
    try:
        bars, pages = _fetch(feed, now)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(
        bars,
        pip_size=float(pair.pip_size),
    ) if bars else {
        "available": False,
        "median_pips": None,
    }
    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target": HISTORY_TARGET,
        "history_actual": len(bars),
        "history_pages": pages,
        "spread_proxy": spread,
    }
    if len(bars) < 40_000 or not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "promotion_eligible": False,
        }
    else:
        validation = _validation_cfg()
        base_costs, stressed_costs = _costs(
            validation,
            float(spread["median_pips"]),
        )
        details["decision"] = evaluate_v27(
            bars,
            pip_size=float(pair.pip_size),
            base_costs=base_costs,
            stressed_costs=stressed_costs,
        )

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details=details,
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(os.getenv(
        "V27_EVIDENCE_OUTPUT",
        "artifacts/xau-canonical-gate-attribution-v27.json",
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    d = details["decision"]
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(
            f"V27_RESULT stage=DATA_INSUFFICIENT history={len(bars)} artifact={path}"
        )
    else:
        print(
            "V27_RESULT "
            f"m15={d['history']['m15_rows']} "
            f"gates={json.dumps(d['gate_stats'], sort_keys=True)} "
            f"signals={json.dumps(d['signal_counts'], sort_keys=True)} "
            f"promotion_eligible=0 artifact={path}"
        )
        for row in d["candidates"]:
            dm=row["development_stressed"]
            hm=row["holdout_stressed"]
            hf=row["holdout_frequency"]
            print(
                "V27_CANDIDATE "
                f"mode={row['mode']} r={row['target_r']} raw={row['raw_signals']} "
                f"dev_n={dm['completed_trades']} dev_pf={dm['profit_factor']} "
                f"dev_exp={dm['expectancy_r']} "
                f"hold_n={hm['completed_trades']} hold_pf={hm['profit_factor']} "
                f"hold_exp={hm['expectancy_r']} "
                f"hold_mean={hf['mean_trades_per_day']} "
                f"hold_ge5={hf['days_ge_5_fraction']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

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
from .research_volatile_cfd_m15_router_v26 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOLS,
    evaluate_v26,
)
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_volatile_cfd_m15_router_v26"
HISTORY_TARGET = 50_000
MIN_HISTORY = 30_000
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
            feed = build_ctrader_research_feed(policy, SYMBOLS)
            feed.ensure_connected()
            return feed
        except CollectorUnavailable as exc:
            last = exc
            if "connection timeout" not in str(exc).lower():
                raise
    raise CollectorUnavailable("V26_CTRADER_CONNECT_RETRY_EXHAUSTED") from last


def _fetch(feed, symbol: str, as_of: datetime):
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
                symbol,
                "M15",
                from_time=cursor - timedelta(seconds=count * TIMEFRAME_SECONDS * 3),
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
        if x.timestamp.astimezone(UTC) + timedelta(seconds=TIMEFRAME_SECONDS) <= as_of
    )
    return (
        closed[-HISTORY_TARGET:] if len(closed) > HISTORY_TARGET else closed,
        pages,
    )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V26_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V26_REQUIRE_DEMO")

    configured = {p.symbol: p for p in cfg.pairs}
    if any(symbol not in configured for symbol in SYMBOLS):
        raise SystemExit("V26_SYMBOL_CONFIG_MISMATCH")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = _feed(policy)
    datasets = {}
    evidence = {}
    try:
        for symbol in SYMBOLS:
            bars, pages = _fetch(feed, symbol, now)
            pair = configured[symbol]
            spread = infer_spread_proxy_pips(
                bars,
                pip_size=float(pair.pip_size),
            ) if bars else {
                "available": False,
                "median_pips": None,
            }
            evidence[symbol] = {
                "bars": len(bars),
                "pages": pages,
                "spread_proxy": spread,
            }
            if len(bars) < MIN_HISTORY or not bool(spread.get("available")):
                continue
            base_costs, stress_costs = _costs(
                validation,
                float(spread["median_pips"]),
            )
            datasets[symbol] = (
                bars,
                float(pair.pip_size),
                base_costs,
                stress_costs,
            )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    details = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target_per_symbol": HISTORY_TARGET,
        "minimum_history_per_symbol": MIN_HISTORY,
        "data_evidence": evidence,
    }
    if len(datasets) < 4:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "usable_symbols": list(datasets),
            "promotion_eligible": False,
        }
    else:
        details["decision"] = evaluate_v26(
            datasets,
            validation_cfg=validation,
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
        "V26_EVIDENCE_OUTPUT",
        "artifacts/volatile-cfd-m15-router-v26.json",
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
            f"V26_RESULT stage=DATA_INSUFFICIENT usable={d['usable_symbols']} artifact={path}"
        )
    else:
        m=d["aggregate_holdout_stressed"]
        f=d["aggregate_holdout_frequency"]
        print(
            "V26_RESULT "
            f"symbols={len(d['symbols'])} selected={d['selected_symbols']} "
            f"positive={d['positive_holdout_symbols']} "
            f"n={m['completed_trades']} pf={m['profit_factor']} exp={m['expectancy_r']} "
            f"mean_day={f['mean_trades_per_day']} ge5={f['days_ge_5_fraction']} "
            f"quality={int(d['aggregate_quality_pass'])} breadth={int(d['breadth_pass'])} "
            f"frequency={int(d['frequency_pass'])} candidate={int(d['forward_shadow_candidate'])} "
            f"promotion_eligible=0 artifact={path}"
        )
        for symbol,row in sorted(d["symbol_results"].items()):
            sel=row["selected"]
            if sel is None:
                print(f"V26_SYMBOL symbol={symbol} selected=NONE")
            else:
                hm=sel["holdout_stressed"]; hf=sel["holdout_frequency"]
                print(
                    "V26_SYMBOL "
                    f"symbol={symbol} variant={sel['variant_id']} "
                    f"dev_pf={sel['development_stressed']['profit_factor']} "
                    f"dev_exp={sel['development_stressed']['expectancy_r']} "
                    f"wf={sel['walk_forward']['pass_fraction']} "
                    f"hold_n={hm['completed_trades']} hold_pf={hm['profit_factor']} "
                    f"hold_exp={hm['expectancy_r']} hold_mean={hf['mean_trades_per_day']} "
                    f"pass={int(sel['holdout_passed'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

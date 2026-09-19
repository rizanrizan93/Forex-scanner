from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .exceptions import CollectorUnavailable
from .research_per_symbol_router_v19 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOLS,
    evaluate,
)
from .research_multisymbol_m15_breakout_v18 import TIMEFRAME_SECONDS
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_per_symbol_router_v19"
HISTORY_TARGET = 50_000
MIN_HISTORY = 30_000
PAGE_BARS = 5_000
MAX_PAGES = 12


def _fetch(feed, symbol: str, as_of: datetime):
    merged = {}
    cursor = as_of
    pages = []
    prev = None
    for page in range(1, MAX_PAGES + 1):
        remaining = HISTORY_TARGET - len(merged)
        if remaining <= 0:
            break
        count = min(PAGE_BARS, remaining)
        try:
            got = tuple(feed.historical_bars(
                symbol, "M15",
                from_time=cursor - timedelta(seconds=count * TIMEFRAME_SECONDS * 3),
                to_time=cursor,
                count=count,
            ))
        except CollectorUnavailable:
            pages.append({"page": page, "received": 0, "terminal": "COLLECTOR_UNAVAILABLE"})
            break
        if not got:
            break
        for row in got:
            merged[row.timestamp] = row
        earliest = min(row.timestamp for row in got)
        pages.append({
            "page": page,
            "received": len(got),
            "merged": len(merged),
            "earliest": earliest.isoformat(),
            "latest": max(row.timestamp for row in got).isoformat(),
        })
        if prev is not None and earliest >= prev:
            break
        prev = earliest
        cursor = earliest - timedelta(seconds=1)
    rows = tuple(sorted(merged.values(), key=lambda x: x.timestamp))
    closed = tuple(
        x for x in rows
        if x.timestamp.astimezone(UTC) + timedelta(seconds=TIMEFRAME_SECONDS) <= as_of
    )
    return closed[-HISTORY_TARGET:] if len(closed) > HISTORY_TARGET else closed, pages


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V19_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V19_REQUIRE_DEMO")

    configured = {p.symbol: p for p in cfg.pairs}
    requested = tuple(s for s in SYMBOLS if s in configured)
    if len(requested) != len(SYMBOLS):
        raise SystemExit("V19_SYMBOL_CONFIG_MISMATCH")

    now = datetime.now(tz=UTC)
    validation = _validation_cfg()
    feed = build_ctrader_research_feed(policy, requested)
    datasets = {}
    evidence: dict[str, Any] = {}
    try:
        feed.ensure_connected()
        for symbol in requested:
            bars, pages = _fetch(feed, symbol, now)
            pair = configured[symbol]
            spread = infer_spread_proxy_pips(bars, pip_size=float(pair.pip_size)) if bars else {
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
            base_costs, stress_costs = _costs(validation, float(spread["median_pips"]))
            datasets[symbol] = (bars, float(pair.pip_size), base_costs, stress_costs)
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

    if len(datasets) < 14:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "usable_symbols": list(datasets),
            "promotion_eligible": False,
            "forward_demo_eligible": False,
        }
    else:
        details["decision"] = evaluate(datasets, validation_cfg=validation)

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME, healthy=True, lag_seconds=0.0, details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(os.getenv(
        "V19_EVIDENCE_OUTPUT",
        "artifacts/per-symbol-router-v19.json",
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    d = details["decision"]
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(f"V19 stage=DATA_INSUFFICIENT usable={len(d['usable_symbols'])} artifact={path}")
    else:
        m=d["aggregate_holdout_stressed"]; f=d["aggregate_holdout_frequency"]
        print(
            "V19_RESULT "
            f"symbols={len(d['symbols'])} selected_symbols={len(d['selected_symbols'])} "
            f"positive_holdout_symbols={len(d['holdout_positive_symbols'])} "
            f"hold_n={m['completed_trades']} hold_pf={m['profit_factor']} "
            f"hold_exp={m['expectancy_r']} hold_mean={f['mean_trades_per_day']} "
            f"hold_ge5={f['days_ge_5_fraction']} quality={int(d['aggregate_quality_pass'])} "
            f"frequency={int(d['aggregate_frequency_pass'])} breadth={int(d['breadth_pass'])} "
            f"forward_demo_eligible={int(d['forward_demo_eligible'])} "
            f"promotion_eligible=0 artifact={path}"
        )
        for symbol,row in sorted(d["symbol_results"].items()):
            selected=row["selected"]
            if selected is None:
                print(f"V19_SYMBOL symbol={symbol} selected=NONE")
            else:
                hm=selected["holdout_stressed"]
                print(
                    "V19_SYMBOL "
                    f"symbol={symbol} family={selected['family']} "
                    f"dev_pf={selected['development_stressed']['profit_factor']} "
                    f"dev_exp={selected['development_stressed']['expectancy_r']} "
                    f"wf={selected['walk_forward']['pass_fraction']} "
                    f"hold_n={hm['completed_trades']} hold_pf={hm['profit_factor']} "
                    f"hold_exp={hm['expectancy_r']} hold_pass={int(selected['holdout_passed'])}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

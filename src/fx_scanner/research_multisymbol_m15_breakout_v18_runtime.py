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
from .research_multisymbol_m15_breakout_v18 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOLS,
    TIMEFRAME_SECONDS,
    evaluate,
)
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_multisymbol_m15_breakout_v18"
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
            "page": page, "received": len(got), "merged": len(merged),
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
        raise SystemExit("V18_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V18_REQUIRE_DEMO")

    configured = {p.symbol: p for p in cfg.pairs}
    requested = tuple(s for s in SYMBOLS if s in configured)
    if len(requested) != len(SYMBOLS):
        raise SystemExit("V18_SYMBOL_CONFIG_MISMATCH")

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
                "available": False, "median_pips": None,
            }
            evidence[symbol] = {
                "bars": len(bars), "pages": pages, "spread_proxy": spread,
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

    if len(datasets) < 7:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "usable_symbols": list(datasets),
            "promotion_eligible": False,
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
        "V18_EVIDENCE_OUTPUT",
        "artifacts/multisymbol-m15-breakout-v18.json",
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    d = details["decision"]
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(f"V18 stage=DATA_INSUFFICIENT usable={len(d['usable_symbols'])} artifact={path}")
    else:
        print(
            "V18_RESULT "
            f"symbols={len(d['symbols'])} selected={d['selected_variant']} "
            f"promotion_eligible={int(bool(d['promotion_eligible']))} artifact={path}"
        )
        for row in d["variants"]:
            m=row["development_stressed"]; f=row["development_frequency"]
            h=row["holdout_stressed"]; hf=row["holdout_frequency"]
            print(
                "V18_VARIANT "
                f"id={row['variant']['variant_id']} dev_n={m['completed_trades']} "
                f"dev_pf={m['profit_factor']} dev_exp={m['expectancy_r']} "
                f"dev_mean={f['mean_trades_per_day']} dev_ge5={f['days_ge_5_fraction']} "
                f"wf={row['walk_forward']['pass_fraction']} dev_pass={int(row['development_passed'])} "
                f"hold_n={h['completed_trades']} hold_pf={h['profit_factor']} hold_exp={h['expectancy_r']} "
                f"hold_mean={hf['mean_trades_per_day']} hold_ge5={hf['days_ge_5_fraction']} "
                f"hold_pass={int(row['holdout_passed'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

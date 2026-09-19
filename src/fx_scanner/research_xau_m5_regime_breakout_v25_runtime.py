from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .exceptions import CollectorUnavailable
from .research_xau_m5_history import fetch_exact_m5_history
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .research_xau_m5_regime_breakout_v25 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_v25,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_m5_regime_breakout_v25"
HISTORY_TARGET = 300_000
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
    raise CollectorUnavailable("V25_CTRADER_CONNECT_RETRY_EXHAUSTED") from last


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V25_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V25_REQUIRE_DEMO")
    pair = next((p for p in cfg.pairs if p.symbol == SYMBOL), None)
    if pair is None:
        raise SystemExit("V25_XAU_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = _feed(policy)
    try:
        bars, pages = fetch_exact_m5_history(
            feed,
            target=HISTORY_TARGET,
            as_of=now,
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=float(pair.pip_size)) if bars else {
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

    if len(bars) < 250_000 or not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "promotion_eligible": False,
        }
    else:
        validation = _validation_cfg()
        base_costs, stress_costs = _costs(
            validation,
            float(spread["median_pips"]),
        )
        details["decision"] = evaluate_v25(
            bars,
            costs=base_costs,
            stressed_costs=stress_costs,
            validation_cfg=validation,
        )

    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME, healthy=True, lag_seconds=0.0, details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"] = f"{type(exc).__name__}:{exc}"

    path = Path(os.getenv(
        "V25_EVIDENCE_OUTPUT",
        "artifacts/xau-m5-regime-breakout-v25.json",
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    d = details["decision"]
    if d.get("stage") == "DATA_INSUFFICIENT":
        print(f"V25_RESULT stage=DATA_INSUFFICIENT history={len(bars)} artifact={path}")
    else:
        print(
            "V25_RESULT "
            f"m5={d['m5_bars']} selected={d['selected_variant']} "
            f"holdout_opened={int(d['holdout'] is not None)} promotion_eligible=0 artifact={path}"
        )
        for row in d["variants"]:
            m=row["development_stressed"]; f=row["development_frequency"]
            print(
                "V25_VARIANT "
                f"id={row['variant']['variant_id']} n={m['completed_trades']} "
                f"win={m['win_rate']} pf={m['profit_factor']} exp={m['expectancy_r']} "
                f"mean_day={f['mean_trades_per_day']} ge5={f['days_ge_5_fraction']} "
                f"wf={row['walk_forward']['pass_fraction']} passed={int(row['development_passed'])}"
            )
        if d["holdout"]:
            h=d["holdout"]; m=h["stressed"]; f=h["frequency"]
            print(
                "V25_HOLDOUT "
                f"id={h['variant_id']} n={m['completed_trades']} win={m['win_rate']} "
                f"pf={m['profit_factor']} exp={m['expectancy_r']} "
                f"mean_day={f['mean_trades_per_day']} ge5={f['days_ge_5_fraction']} "
                f"positive={int(h['quality_positive'])} five_per_day={int(h['five_per_day_reached'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_h1_m15_m5_trend_v9 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_h1_m15_m5_trend_v9,
)
from .research_xau_m15_continuation_tournament import PIP_SIZE
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .research_xau_m5_history import fetch_exact_m5_history
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_h1_m15_m5_trend_v9"
HISTORY_BARS = 300_000


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_TREND_V9_DEMO_ONLY")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_TREND_V9_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = fetch_exact_m5_history(feed, target=HISTORY_BARS, as_of=now)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    spread = infer_spread_proxy_pips(bars, pip_size=PIP_SIZE) if bars else {
        "available": False,
        "coverage": 0.0,
        "median_pips": None,
    }
    details: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target_bars": HISTORY_BARS,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
        "spread_proxy": spread,
    }

    if len(bars) != HISTORY_BARS or not bool(spread.get("available")):
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": (
                f"M5_HISTORY_TARGET_NOT_MET:{len(bars)}!={HISTORY_BARS}"
                if len(bars) != HISTORY_BARS
                else "CTRADER_SPREAD_PROXY_UNAVAILABLE"
            ),
            "promotion_eligible": False,
        }
    else:
        validation_cfg = _validation_cfg()
        base_costs, stressed_costs = _costs(
            validation_cfg,
            float(spread["median_pips"]),
        )
        details["decision"] = evaluate_h1_m15_m5_trend_v9(
            bars,
            costs=base_costs,
            stressed_costs=stressed_costs,
            validation_cfg=validation_cfg,
        )

    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )
    path = Path(
        os.getenv(
            "XAU_TREND_V9_EVIDENCE_OUTPUT",
            "artifacts/xau-h1-m15-m5-trend-v9.json",
        )
    )
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
    decision = details["decision"]
    if decision.get("stage") == "DATA_INSUFFICIENT":
        print(f"CTRADER_XAU_TREND_V9 stage=DATA_INSUFFICIENT artifact={path}")
    else:
        print(
            "CTRADER_XAU_TREND_V9 "
            f"selected={decision['selected_variant']} "
            f"holdout_opened={int(decision['holdout'] is not None)} "
            f"promotion_eligible={int(bool(decision['promotion_eligible']))} "
            f"artifact={path} execution_influence=0"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

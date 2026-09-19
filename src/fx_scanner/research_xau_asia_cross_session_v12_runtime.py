from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_asia_cross_session_v12 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_asia_cross_session_v12,
)
from .research_xau_h1_history import fetch_h1_history
from .research_xau_m15_continuation_tournament import PIP_SIZE
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs, _validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_asia_cross_session_v12"
HISTORY_TARGET = 80_000
MIN_ACCEPTABLE_BARS = 30_000


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V12_DEMO_ONLY")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_V12_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages, source_exhausted = fetch_h1_history(
            feed,
            target=HISTORY_TARGET,
            as_of=now,
        )
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
        "history_target_bars": HISTORY_TARGET,
        "history_actual_closed_bars": len(bars),
        "history_source_exhausted": source_exhausted,
        "history_pages": pages,
        "spread_proxy": spread,
    }

    insufficient = bool(
        len(bars) < MIN_ACCEPTABLE_BARS
        or (len(bars) < HISTORY_TARGET and not source_exhausted)
        or not bool(spread.get("available"))
    )
    if insufficient:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": f"H1_HISTORY_INCOMPLETE:{len(bars)}:source_exhausted={int(source_exhausted)}",
            "promotion_eligible": False,
        }
    else:
        cfg_validation = _validation_cfg()
        base_costs, stress_costs = _costs(
            cfg_validation,
            float(spread["median_pips"]),
        )
        details["decision"] = evaluate_asia_cross_session_v12(
            bars,
            costs=base_costs,
            stressed_costs=stress_costs,
            validation_cfg=cfg_validation,
        )

    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )
    path = Path(
        os.getenv(
            "XAU_V12_EVIDENCE_OUTPUT",
            "artifacts/xau-asia-cross-session-v12.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "artifact_contract": ARTIFACT_CONTRACT,
        "contains_secrets": False,
        "details": details,
    }, indent=2, sort_keys=True, default=str) + "\n")

    decision = details["decision"]
    if decision.get("stage") == "DATA_INSUFFICIENT":
        print(f"CTRADER_XAU_V12 stage=DATA_INSUFFICIENT artifact={path}")
    else:
        print(
            "CTRADER_XAU_V12 "
            f"bars={len(bars)} selected={decision['selected_variant']} "
            f"holdout_opened={int(decision['holdout'] is not None)} "
            f"promotion_eligible={int(bool(decision['promotion_eligible']))} "
            f"artifact={path} execution_influence=0"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

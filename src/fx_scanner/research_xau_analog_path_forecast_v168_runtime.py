from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .research_xau_analog_path_forecast_v168 import (
    ARTIFACT_CONTRACT,
    RESEARCH_VERSION,
    SYMBOL,
    evaluate_analog_path_forecast_v168,
)
from .research_xau_m15_dual_strategy_runtime import (
    MIN_HISTORY_BARS,
    _fetch_history,
)
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_xau_analog_path_forecast_v168"
HISTORY_TARGET = 100_000


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_ANALOG_PATH_V168_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_ANALOG_PATH_V168_REQUIRE_DEMO")
    if SYMBOL not in {pair.symbol for pair in cfg.pairs}:
        raise SystemExit("XAU_ANALOG_PATH_V168_SYMBOL_NOT_CONFIGURED")

    now = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        bars, pages = _fetch_history(feed, target=HISTORY_TARGET, as_of=now)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    details: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "observed_at": now.isoformat(),
        "history_target_bars": HISTORY_TARGET,
        "history_actual_closed_bars": len(bars),
        "history_pages": pages,
    }
    if len(bars) < MIN_HISTORY_BARS:
        details["decision"] = {
            "stage": "DATA_INSUFFICIENT",
            "reason": f"M15_HISTORY_BELOW_MINIMUM:{len(bars)}<{MIN_HISTORY_BARS}",
            "promotion_eligible": False,
        }
    else:
        details["decision"] = evaluate_analog_path_forecast_v168(bars)

    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=True,
        lag_seconds=0.0,
        details=details,
    )

    path = Path(
        os.getenv(
            "XAU_ANALOG_PATH_V168_EVIDENCE_OUTPUT",
            "artifacts/xau-analog-path-forecast-v168.json",
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
        print(
            f"XAU_ANALOG_PATH_V168 stage=DATA_INSUFFICIENT "
            f"bars={len(bars)} artifact={path} execution_influence=0"
        )
    else:
        validation = decision["validation"]
        current = decision.get("current_forecast")
        print(
            "XAU_ANALOG_PATH_V168 "
            f"bars={len(bars)} states={decision['analog_states']} "
            f"eval={validation['evaluation_points']} "
            f"brier_skill={validation['brier_skill_score']} "
            f"first_hit_acc={validation['first_hit_top1_accuracy']} "
            f"path_acc={validation['path_top1_accuracy']} "
            f"current_path={None if current is None else current['path_top']} "
            f"artifact={path} execution_influence=0"
        )
        if current is not None:
            print(
                "V168_CURRENT "
                + json.dumps(
                    {
                        "as_of": current["as_of"],
                        "price": current["price"],
                        "session": current["session"],
                        "atr": current["atr"],
                        "first_hit_probabilities": current["first_hit_probabilities"],
                        "path_probabilities": current["path_probabilities"],
                        "confidence_entropy": current["confidence_entropy"],
                        "return_atr": current["return_atr"],
                        "excursion_atr": current["excursion_atr"],
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

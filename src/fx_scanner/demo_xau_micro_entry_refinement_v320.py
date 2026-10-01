from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore
from .xau_rizan_micro_entry_refinement_v320 import (
    CONTRACT,
    build_micro_entry_refinement,
)

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_micro_entry_refinement_v320"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"
M5_LOOKBACK_DAYS = 4
M15_LOOKBACK_DAYS = 12
M5_COUNT = 1400
M15_COUNT = 1200


def _latest_atlas(store: SupabaseOperationalStore) -> dict[str, Any] | None:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", ATLAS_WORKER)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = [dict(row or {}) for row in (response.data or [])]
    return rows[0] if rows else None


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment") or "").upper() != "DEMO":
        raise SystemExit("XAU_MICRO_ENTRY_V320_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_MICRO_ENTRY_V320_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_MICRO_ENTRY_V320_SYMBOL_NOT_CONFIGURED")

    store = SupabaseOperationalStore.from_env()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    now = datetime.now(tz=UTC)
    evaluation: dict[str, Any] = {}
    error: str | None = None
    raw_m5_count = 0
    raw_m15_count = 0

    try:
        atlas_hb = _latest_atlas(store)
        if not atlas_hb or not bool(atlas_hb.get("healthy")):
            raise RuntimeError("V182_ATLAS_UNAVAILABLE")
        atlas_eval = dict(dict(atlas_hb.get("details") or {}).get("evaluation") or {})
        if not atlas_eval:
            raise RuntimeError("V182_ATLAS_EMPTY")

        feed.ensure_connected()
        bars_m5 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=now - timedelta(days=M5_LOOKBACK_DAYS),
                to_time=now,
                count=M5_COUNT,
            )
        )
        bars_m15 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=now - timedelta(days=M15_LOOKBACK_DAYS),
                to_time=now,
                count=M15_COUNT,
            )
        )
        raw_m5_count = len(bars_m5)
        raw_m15_count = len(bars_m15)
        price_now = (
            float(bars_m5[-1].close)
            if bars_m5
            else float(bars_m15[-1].close)
            if bars_m15
            else None
        )
        evaluation = build_micro_entry_refinement(
            atlas_evaluation=atlas_eval,
            bars_m5=bars_m5,
            bars_m15=bars_m15,
            price_now=price_now,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "raw_m5_bars": raw_m5_count,
            "raw_m15_bars": raw_m15_count,
            "evaluation": evaluation,
            "error": error,
            "execution_authority": False,
            "execution_influence": False,
            "live_execution_enabled": False,
        },
    )
    print(
        "CTRADER_DEMO_XAU_MICRO_ENTRY_V320 "
        f"healthy={int(healthy)} "
        f"state={evaluation.get('state','ERROR')} "
        f"direction={evaluation.get('direction','WAIT')} "
        f"phase={evaluation.get('phase','WAIT')} "
        "execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

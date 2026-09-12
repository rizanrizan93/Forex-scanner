from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import load_project_config
from .demo_five_core_candidate_producer import (
    _history_window_seconds,
    _subset_cfg,
    _with_history_requirements,
)
from .demo_five_core_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    evaluation_key,
    xau_d1_evaluation_snapshot,
)
from .demo_five_core_router import PAIR_STRATEGY_IDS, evaluate_xau_d1_tsmom_60_200
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_xau_d1_forward_evidence"
EVALUATION_EVENT = "DEMO_FIVE_CORE_D1_EVALUATION"
XAU_SYMBOL = "XAUUSD"
REQUEST_COUNT = 232


def _already_recorded(store: Any, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVALUATION_EVENT)
            .eq("code", PAIR_STRATEGY_IDS[XAU_SYMBOL])
            .order("observed_at", desc=True)
            .limit(100)
            .execute()
        )
    except Exception:
        # Evidence observer is fail-closed with respect to its own durability:
        # never create an uncertain duplicate if the dedupe read is unavailable.
        return True
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if str(payload.get("evaluation_key") or "") == key:
            return True
    return False


def _persist_evaluation(store: Any, *, snapshot: dict[str, Any], key: str) -> bool:
    if _already_recorded(store, key):
        return False
    account_id = os.getenv("CTRADER_ACCOUNT_ID", os.getenv("CTRADER_TRADER_LOGIN", "")).strip()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_FORWARD_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"FIVE_CORE_EVAL:{digest}",
        broker_order_id=None,
        event_type=EVALUATION_EVENT,
        accepted=None,
        code=PAIR_STRATEGY_IDS[XAU_SYMBOL],
        message="non-authoritative XAU D1 forward strategy evaluation",
        payload={
            "evaluation_key": key,
            "environment": "DEMO",
            "execution_influence": False,
            "forward_evidence_contract": FORWARD_EVIDENCE_CONTRACT,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "evaluation": snapshot,
        },
    )
    return True


def run() -> int:
    cfg = _with_history_requirements(_subset_cfg(load_project_config(None), (XAU_SYMBOL,)))
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_FORWARD_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_FORWARD_EVIDENCE_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, (XAU_SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    snapshot: dict[str, Any] = {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "execution_influence": False,
        "symbol": XAU_SYMBOL,
        "strategy_id": PAIR_STRATEGY_IDS[XAU_SYMBOL],
        "observed_at": as_of.isoformat(),
        "closed_bars": 0,
        "reason": "NOT_EVALUATED",
    }
    persisted = False
    duplicate_or_unavailable = False
    error: str | None = None

    try:
        feed.ensure_connected()
        timeframe_seconds = int(cfg.timeframes["D1"])
        start = as_of - timedelta(
            seconds=_history_window_seconds("D1", REQUEST_COUNT, timeframe_seconds)
        )
        bars = tuple(
            feed.historical_bars(
                XAU_SYMBOL,
                "D1",
                from_time=start,
                to_time=as_of,
                count=REQUEST_COUNT,
            )
        )
        signal = evaluate_xau_d1_tsmom_60_200(bars, as_of=as_of)
        snapshot = xau_d1_evaluation_snapshot(bars, as_of=as_of, signal=signal)
        key = evaluation_key(snapshot)
        if key is not None:
            persisted = _persist_evaluation(store, snapshot=snapshot, key=key)
            duplicate_or_unavailable = not persisted
        else:
            error = "FORWARD_EVIDENCE_INSUFFICIENT_D1_HISTORY"
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
            "mode": "XAU_D1_FORWARD_EVIDENCE_V1",
            "environment": "DEMO",
            "execution_influence": False,
            "quote_dependency": False,
            "event_type": EVALUATION_EVENT,
            "persisted_new_evaluation": persisted,
            "duplicate_or_dedupe_unavailable": duplicate_or_unavailable,
            "evaluation": snapshot,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_XAU_D1_FORWARD_EVIDENCE "
        f"healthy={healthy} bars={snapshot.get('closed_bars')} "
        f"direction={snapshot.get('direction')} active={snapshot.get('active')} "
        f"reason={snapshot.get('reason')} persisted={persisted}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

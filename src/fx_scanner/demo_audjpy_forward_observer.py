from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .demo_audjpy_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    STRATEGY_ID,
    SYMBOL,
    audjpy_h4_evaluation_snapshot,
    evaluation_key,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_audjpy_h4_forward_evidence"
EVALUATION_EVENT = "DEMO_WATCH_PAIR_H4_EVALUATION"
REQUEST_COUNT = 260
LOOKBACK_DAYS = 90


def _resolve_account_id() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _already_recorded(store: Any, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVALUATION_EVENT)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(100)
            .execute()
        )
    except Exception:
        # Fail closed: if dedupe state cannot be read, do not risk uncertain duplicate evidence.
        return True
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if str(payload.get("evaluation_key") or "") == key:
            return True
    return False


def _persist_evaluation(store: Any, *, snapshot: dict[str, Any], key: str) -> bool:
    if _already_recorded(store, key):
        return False
    account_id = _resolve_account_id()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_AUDJPY_FORWARD_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"AUDJPY_H4_EVAL:{digest}",
        broker_order_id=None,
        event_type=EVALUATION_EVENT,
        accepted=None,
        code=STRATEGY_ID,
        message="non-authoritative AUDJPY H4 forward strategy evaluation",
        payload={
            "evaluation_key": key,
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "forward_evidence_contract": FORWARD_EVIDENCE_CONTRACT,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "evaluation": snapshot,
        },
    )
    return True


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("AUDJPY_FORWARD_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("AUDJPY_FORWARD_EVIDENCE_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    snapshot: dict[str, Any] = {
        "contract": FORWARD_EVIDENCE_CONTRACT,
        "execution_influence": False,
        "symbol": SYMBOL,
        "strategy_id": STRATEGY_ID,
        "observed_at": as_of.isoformat(),
        "closed_bars": 0,
        "reason": "NOT_EVALUATED",
    }
    persisted = False
    duplicate_or_unavailable = False
    error: str | None = None

    try:
        feed.ensure_connected()
        bars = tuple(
            feed.historical_bars(
                SYMBOL,
                "H4",
                from_time=as_of - timedelta(days=LOOKBACK_DAYS),
                to_time=as_of,
                count=REQUEST_COUNT,
            )
        )
        snapshot = audjpy_h4_evaluation_snapshot(bars, as_of=as_of)
        key = evaluation_key(snapshot)
        if key is None:
            error = "AUDJPY_FORWARD_EVIDENCE_INSUFFICIENT_H4_HISTORY"
        else:
            persisted = _persist_evaluation(store, snapshot=snapshot, key=key)
            duplicate_or_unavailable = not persisted
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
            "mode": "AUDJPY_H4_FORWARD_EVIDENCE_V1",
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "quote_dependency": False,
            "event_type": EVALUATION_EVENT,
            "persisted_new_evaluation": persisted,
            "duplicate_or_dedupe_unavailable": duplicate_or_unavailable,
            "evaluation": snapshot,
            "error": error,
        },
    )
    print(
        "CTRADER_DEMO_AUDJPY_H4_FORWARD_EVIDENCE "
        f"healthy={healthy} bars={snapshot.get('closed_bars')} "
        f"direction={snapshot.get('direction')} active={snapshot.get('active')} "
        f"reason={snapshot.get('reason')} persisted={persisted}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

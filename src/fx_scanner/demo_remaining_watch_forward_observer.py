from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .demo_remaining_watch_forward_evidence import (
    FORWARD_EVIDENCE_CONTRACT,
    PAIR_SPECS,
    evaluate_remaining_watch_pair,
    evaluation_key,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_remaining_watch_forward_evidence"
EVALUATION_EVENT = "DEMO_REMAINING_WATCH_FORWARD_EVALUATION"


def _resolve_account_id() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _already_recorded(store: Any, *, strategy_id: str, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVALUATION_EVENT)
            .eq("code", strategy_id)
            .order("observed_at", desc=True)
            .limit(200)
            .execute()
        )
    except Exception:
        # Fail closed with respect to evidence durability: no uncertain duplicate writes.
        return True
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if str(payload.get("evaluation_key") or "") == key:
            return True
    return False


def _persist_evaluation(
    store: Any,
    *,
    snapshot: dict[str, Any],
    key: str,
) -> bool:
    strategy_id = str(snapshot["strategy_id"])
    if _already_recorded(store, strategy_id=strategy_id, key=key):
        return False
    account_id = _resolve_account_id()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_REMAINING_WATCH_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    symbol = str(snapshot["symbol"])
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"REMAINING_WATCH_EVAL:{symbol}:{digest}",
        broker_order_id=None,
        event_type=EVALUATION_EVENT,
        accepted=None,
        code=strategy_id,
        message=f"non-authoritative {symbol} forward strategy evaluation",
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


def _history_request(symbol: str, as_of: datetime) -> tuple[str, datetime, int]:
    timeframe = str(PAIR_SPECS[symbol]["timeframe"])
    if timeframe == "D1":
        return timeframe, as_of - timedelta(days=500), 260
    return timeframe, as_of - timedelta(days=120), 360


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("REMAINING_WATCH_FORWARD_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("REMAINING_WATCH_FORWARD_EVIDENCE_REQUIRE_DEMO")

    symbols = tuple(PAIR_SPECS)
    feed = build_ctrader_research_feed(policy, symbols)
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    evaluations: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    try:
        feed.ensure_connected()
        for symbol in symbols:
            try:
                timeframe, start, request_count = _history_request(symbol, as_of)
                bars = tuple(
                    feed.historical_bars(
                        symbol,
                        timeframe,
                        from_time=start,
                        to_time=as_of,
                        count=request_count,
                    )
                )
                snapshot = evaluate_remaining_watch_pair(symbol, bars, as_of=as_of)
                key = evaluation_key(snapshot)
                persisted = False
                duplicate_or_unavailable = False
                if key is None:
                    errors[symbol] = "FORWARD_EVIDENCE_INSUFFICIENT_HISTORY"
                else:
                    persisted = _persist_evaluation(store, snapshot=snapshot, key=key)
                    duplicate_or_unavailable = not persisted
                evaluations[symbol] = {
                    "snapshot": snapshot,
                    "persisted_new_evaluation": persisted,
                    "duplicate_or_dedupe_unavailable": duplicate_or_unavailable,
                }
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}:{exc}"
    except Exception as exc:
        errors["_feed"] = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = not errors and len(evaluations) == len(symbols)
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "mode": "REMAINING_WATCH_FORWARD_EVIDENCE_V1",
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "quote_dependency": False,
            "event_type": EVALUATION_EVENT,
            "evaluations": evaluations,
            "errors": errors,
        },
    )

    for symbol in symbols:
        row = evaluations.get(symbol, {})
        snapshot = dict(row.get("snapshot") or {})
        print(
            "CTRADER_DEMO_REMAINING_WATCH_FORWARD_EVIDENCE "
            f"symbol={symbol} healthy={symbol not in errors} bars={snapshot.get('closed_bars')} "
            f"direction={snapshot.get('direction')} active={snapshot.get('active')} "
            f"reason={snapshot.get('reason')} persisted={row.get('persisted_new_evaluation', False)}"
        )
    if errors:
        print("CTRADER_DEMO_REMAINING_WATCH_FORWARD_ERRORS symbols=" + ",".join(sorted(errors)))
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

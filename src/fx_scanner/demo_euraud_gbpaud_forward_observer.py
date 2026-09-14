from __future__ import annotations

"""Scheduled DEMO/read-only forward observer for EURAUD and GBPAUD.

This worker reads broker-native cTrader D1 history and persists one deduplicated evaluation
per completed signal bar.  It never submits, modifies, or closes broker orders.
"""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from .demo_euraud_gbpaud_forward_evidence import (
    EXECUTION_INFLUENCE,
    FORWARD_EVIDENCE_CONTRACT,
    PROMOTION_AUTHORITY,
    evaluate_euraud,
    evaluate_gbpaud,
    evaluation_key,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_euraud_gbpaud_forward_evidence"
EVALUATION_EVENT = "DEMO_EURAUD_GBPAUD_FORWARD_EVALUATION"
FETCH_SYMBOLS = ("EURAUD", "GBPAUD", "GBPUSD", "AUDUSD")
PRIMARY_SYMBOLS = ("EURAUD", "GBPAUD")
REQUEST_COUNT = 700
LOOKBACK_DAYS = 1_200


def _resolve_account_id() -> str:
    return os.getenv("CTRADER_ACCOUNT_ID", "").strip() or os.getenv("CTRADER_TRADER_LOGIN", "").strip()


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
        # Evidence durability is fail-closed: an uncertain dedupe read must not
        # create duplicate records or silently manufacture forward sample size.
        return True
    for row in response.data or []:
        payload = dict(row.get("payload") or {})
        if str(payload.get("evaluation_key") or "") == key:
            return True
    return False


def _persist_evaluation(store: Any, *, snapshot: dict[str, Any], key: str) -> bool:
    strategy_id = str(snapshot["strategy_id"])
    if _already_recorded(store, strategy_id=strategy_id, key=key):
        return False
    account_id = _resolve_account_id()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_EURAUD_GBPAUD_FORWARD_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    symbol = str(snapshot["symbol"])
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"EURAUD_GBPAUD_FORWARD:{symbol}:{digest}",
        broker_order_id=None,
        event_type=EVALUATION_EVENT,
        accepted=None,
        code=strategy_id,
        message=f"non-authoritative {symbol} frozen-strategy forward evaluation",
        payload={
            "evaluation_key": key,
            "environment": "DEMO",
            "execution_eligible": False,
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
        raise SystemExit("EURAUD_GBPAUD_FORWARD_EVIDENCE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("EURAUD_GBPAUD_FORWARD_EVIDENCE_REQUIRE_DEMO")
    if EXECUTION_INFLUENCE or PROMOTION_AUTHORITY:
        raise SystemExit("EURAUD_GBPAUD_FORWARD_EVIDENCE_AUTHORITY_MUST_REMAIN_FALSE")

    feed = build_ctrader_research_feed(policy, FETCH_SYMBOLS)
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    fetched: dict[str, tuple[Bar, ...]] = {}
    evaluations: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    try:
        feed.ensure_connected()
        for symbol in FETCH_SYMBOLS:
            try:
                fetched[symbol] = tuple(
                    feed.historical_bars(
                        symbol,
                        "D1",
                        from_time=as_of - timedelta(days=LOOKBACK_DAYS),
                        to_time=as_of,
                        count=REQUEST_COUNT,
                    )
                )
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}:{exc}"

        if "EURAUD" in fetched:
            try:
                snapshot = evaluate_euraud(fetched["EURAUD"], as_of=as_of)
                key = evaluation_key(snapshot)
                if key is None:
                    errors["EURAUD"] = "FORWARD_EVIDENCE_INSUFFICIENT_HISTORY"
                else:
                    persisted = _persist_evaluation(store, snapshot=snapshot, key=key)
                    evaluations["EURAUD"] = {
                        "snapshot": snapshot,
                        "persisted_new_evaluation": persisted,
                        "duplicate_or_dedupe_unavailable": not persisted,
                    }
            except Exception as exc:
                errors["EURAUD"] = f"{type(exc).__name__}:{exc}"

        if all(symbol in fetched for symbol in ("GBPAUD", "GBPUSD", "AUDUSD")):
            try:
                snapshot = evaluate_gbpaud(
                    {symbol: fetched[symbol] for symbol in ("GBPAUD", "GBPUSD", "AUDUSD")},
                    as_of=as_of,
                )
                key = evaluation_key(snapshot)
                if key is None:
                    errors["GBPAUD"] = "FORWARD_EVIDENCE_INSUFFICIENT_HISTORY"
                else:
                    persisted = _persist_evaluation(store, snapshot=snapshot, key=key)
                    evaluations["GBPAUD"] = {
                        "snapshot": snapshot,
                        "persisted_new_evaluation": persisted,
                        "duplicate_or_dedupe_unavailable": not persisted,
                    }
            except Exception as exc:
                errors["GBPAUD"] = f"{type(exc).__name__}:{exc}"
        elif "GBPAUD" not in errors:
            errors["GBPAUD"] = "GBPAUD_COMPONENT_BUNDLE_UNAVAILABLE"
    except Exception as exc:
        errors["_feed"] = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = not errors and all(symbol in evaluations for symbol in PRIMARY_SYMBOLS)
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": FORWARD_EVIDENCE_CONTRACT,
            "mode": "EURAUD_GBPAUD_FORWARD_SHADOW_V1",
            "environment": "DEMO",
            "execution_eligible": False,
            "execution_influence": False,
            "promotion_authority": False,
            "broker_order_submission": False,
            "event_type": EVALUATION_EVENT,
            "bar_counts": {symbol: len(rows) for symbol, rows in fetched.items()},
            "evaluations": evaluations,
            "errors": errors,
        },
    )

    for symbol in PRIMARY_SYMBOLS:
        row = evaluations.get(symbol, {})
        snapshot = dict(row.get("snapshot") or {})
        print(
            "CTRADER_DEMO_EURAUD_GBPAUD_FORWARD "
            f"symbol={symbol} healthy={symbol not in errors} bars={snapshot.get('closed_bars')} "
            f"direction={snapshot.get('direction')} active={snapshot.get('active')} "
            f"reason={snapshot.get('reason')} persisted={row.get('persisted_new_evaluation', False)}"
        )
    if errors:
        print("CTRADER_DEMO_EURAUD_GBPAUD_FORWARD_ERRORS symbols=" + ",".join(sorted(errors)))
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

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
from .demo_five_core_soft_ema_research import (
    candidate_payload,
    evaluate_usdjpy_soft_ema,
    evaluate_xau_soft_ema,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_five_core_soft_ema_observer"
EVENT_TYPE = "DEMO_FIVE_CORE_SOFT_EMA_EVALUATION"
CONTRACT = "FIVE_CORE_SOFT_EMA_FORWARD_V2"
REQUEST_COUNT = 232
SYMBOL_TIMEFRAMES = {"XAUUSD": "D1", "USDJPY": "H4"}


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _key(payload: dict[str, object]) -> str | None:
    signal_bar = payload.get("signal_bar_at")
    if not signal_bar:
        return None
    return "|".join(
        [
            str(payload.get("strategy_id") or ""),
            str(signal_bar),
            str(payload.get("direction") or "NONE"),
            str(payload.get("reason") or "UNKNOWN"),
        ]
    )


def _already_recorded(store: Any, *, strategy_id: str, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVENT_TYPE)
            .eq("code", strategy_id)
            .order("observed_at", desc=True)
            .limit(100)
            .execute()
        )
    except Exception:
        return True
    for row in response.data or []:
        raw = dict(row.get("payload") or {})
        if str(raw.get("evaluation_key") or "") == key:
            return True
    return False


def _persist(store: Any, *, payload: dict[str, object], key: str) -> bool:
    strategy_id = str(payload["strategy_id"])
    if _already_recorded(store, strategy_id=strategy_id, key=key):
        return False
    account_id = _account_label()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_SOFT_EMA_EVIDENCE")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"SOFT_EMA_EVAL:{digest}",
        broker_order_id=None,
        event_type=EVENT_TYPE,
        accepted=None,
        code=strategy_id,
        message="read-only soft-EMA forward evaluation",
        payload={
            "evaluation_key": key,
            "contract": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "evaluation": payload,
        },
    )
    return True


def run() -> int:
    cfg = _with_history_requirements(
        _subset_cfg(load_project_config(None), tuple(SYMBOL_TIMEFRAMES))
    )
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("SOFT_EMA_OBSERVER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("SOFT_EMA_OBSERVER_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, tuple(SYMBOL_TIMEFRAMES))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    evaluations: dict[str, dict[str, object]] = {}
    persisted: dict[str, bool] = {}
    errors: dict[str, str] = {}

    try:
        feed.ensure_connected()
        for symbol, timeframe in SYMBOL_TIMEFRAMES.items():
            try:
                timeframe_seconds = int(cfg.timeframes[timeframe])
                start = as_of - timedelta(
                    seconds=_history_window_seconds(
                        timeframe,
                        REQUEST_COUNT,
                        timeframe_seconds,
                    )
                )
                bars = tuple(
                    feed.historical_bars(
                        symbol,
                        timeframe,
                        from_time=start,
                        to_time=as_of,
                        count=REQUEST_COUNT,
                    )
                )
                candidate = (
                    evaluate_xau_soft_ema(bars, as_of=as_of)
                    if symbol == "XAUUSD"
                    else evaluate_usdjpy_soft_ema(bars, as_of=as_of)
                )
                payload = candidate_payload(candidate)
                evaluations[symbol] = payload
                key = _key(payload)
                persisted[symbol] = False if key is None else _persist(
                    store,
                    payload=payload,
                    key=key,
                )
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = not errors
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "mode": CONTRACT,
            "environment": "DEMO",
            "execution_influence": False,
            "quote_dependency": False,
            "evaluations": evaluations,
            "persisted": persisted,
            "errors": errors,
        },
    )
    print(
        "CTRADER_DEMO_FIVE_CORE_SOFT_EMA_OBSERVER "
        f"healthy={healthy} evaluations={len(evaluations)} persisted={sum(persisted.values())}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from .config import load_project_config
from .demo_xau_m15_ema_smc_reclaim import (
    STRATEGY_ID,
    STRATEGY_PROFILE,
    SYMBOL,
    evaluate_xau_m15_ema_smc_reclaim,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_demo_xau_m15_ema_smc_reclaim_observer"
EVENT_TYPE = "DEMO_XAU_M15_EMA_SMC_RECLAIM_EVALUATION"
FORWARD_CONTRACT = "XAU_M15_EMA_SMC_RECLAIM_FORWARD_V1"
M15_REQUEST_COUNT = 280
H1_REQUEST_COUNT = 96


def _account_label() -> str:
    return (
        os.getenv("CTRADER_ACCOUNT_ID", "").strip()
        or os.getenv("CTRADER_TRADER_LOGIN", "").strip()
    )


def _closed_bars(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    timeframe_minutes: int,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(bars, key=lambda value: ensure_utc(value.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=timeframe_minutes) <= now
    )


def _history_start(
    *,
    as_of: datetime,
    timeframe_seconds: int,
    count: int,
    weekend_multiplier: float = 2.2,
) -> datetime:
    # cTrader history is sparse while the market is closed. The multiplier keeps
    # the request window large enough without changing broker execution authority.
    seconds = int(timeframe_seconds * count * weekend_multiplier)
    return ensure_utc(as_of) - timedelta(seconds=max(seconds, timeframe_seconds * count))


def _evaluation_key(payload: dict[str, Any], *, signal_bar_at: datetime) -> str:
    return "|".join(
        (
            STRATEGY_ID,
            ensure_utc(signal_bar_at).isoformat(),
            str(payload.get("selected_direction") or "NONE"),
            str(payload.get("state") or "NO_TRADE"),
            str(payload.get("score") or 0.0),
        )
    )


def _already_recorded(store: Any, key: str) -> bool:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("payload,event_type,code")
            .eq("event_type", EVENT_TYPE)
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(120)
            .execute()
        )
    except Exception:
        # Persistence uncertainty must never create duplicate evidence.
        return True
    return any(
        str(dict(row.get("payload") or {}).get("evaluation_key") or "") == key
        for row in response.data or []
    )


def _persist(
    store: Any,
    *,
    payload: dict[str, Any],
    key: str,
    signal_bar_at: datetime,
) -> bool:
    if _already_recorded(store, key):
        return False
    account_id = _account_label()
    if not account_id:
        raise RuntimeError("CTRADER_ACCOUNT_ID_REQUIRED_FOR_EMA_SMC_RECLAIM")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    store.record_order_event(
        backend="CTRADER",
        account_id=account_id,
        signal_key=f"EMA_SMC_RECLAIM:{digest}",
        broker_order_id=None,
        event_type=EVENT_TYPE,
        accepted=None,
        code=STRATEGY_ID,
        message="XAU M15 EMA/SMC reclaim shadow evaluation; no broker action",
        payload={
            "evaluation_key": key,
            "signal_bar_at": ensure_utc(signal_bar_at).isoformat(),
            "contract": FORWARD_CONTRACT,
            "strategy_profile": STRATEGY_PROFILE,
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "evaluation": payload,
        },
    )
    return True


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("EMA_SMC_RECLAIM_OBSERVER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("EMA_SMC_RECLAIM_OBSERVER_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("EMA_SMC_RECLAIM_XAUUSD_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    evaluation_payload: dict[str, Any] = {}
    persisted = False
    error: str | None = None
    m15_count = 0
    h1_count = 0

    try:
        feed.ensure_connected()
        m15_seconds = int(cfg.timeframes["M15"])
        h1_seconds = int(cfg.timeframes["H1"])
        raw_m15 = tuple(
            feed.historical_bars(
                SYMBOL,
                "M15",
                from_time=_history_start(
                    as_of=as_of,
                    timeframe_seconds=m15_seconds,
                    count=M15_REQUEST_COUNT,
                ),
                to_time=as_of,
                count=M15_REQUEST_COUNT,
            )
        )
        raw_h1 = tuple(
            feed.historical_bars(
                SYMBOL,
                "H1",
                from_time=_history_start(
                    as_of=as_of,
                    timeframe_seconds=h1_seconds,
                    count=H1_REQUEST_COUNT,
                ),
                to_time=as_of,
                count=H1_REQUEST_COUNT,
            )
        )
        m15 = _closed_bars(raw_m15, as_of=as_of, timeframe_minutes=15)
        h1 = _closed_bars(raw_h1, as_of=as_of, timeframe_minutes=60)
        m15_count = len(m15)
        h1_count = len(h1)
        evaluation = evaluate_xau_m15_ema_smc_reclaim(m15, h1)
        evaluation_payload = evaluation.to_payload()
        if not m15:
            raise RuntimeError("EMA_SMC_RECLAIM_NO_CLOSED_M15")
        signal_bar_at = ensure_utc(m15[-1].timestamp)
        key = _evaluation_key(evaluation_payload, signal_bar_at=signal_bar_at)
        persisted = _persist(
            store,
            payload=evaluation_payload,
            key=key,
            signal_bar_at=signal_bar_at,
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
            "contract": FORWARD_CONTRACT,
            "strategy_id": STRATEGY_ID,
            "environment": "DEMO",
            "execution_influence": False,
            "promotion_authority": False,
            "m15_closed_bars": m15_count,
            "h1_closed_bars": h1_count,
            "persisted": persisted,
            "evaluation": evaluation_payload,
            "error": error,
        },
    )
    state = str(evaluation_payload.get("state") or "ERROR")
    score = evaluation_payload.get("score")
    score_text = "NONE" if score is None else f"{float(score):.2f}"
    print(
        "CTRADER_DEMO_XAU_M15_EMA_SMC_RECLAIM "
        f"healthy={healthy} state={state} score={score_text} "
        f"persisted={persisted} execution_influence=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())

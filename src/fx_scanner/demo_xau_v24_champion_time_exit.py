from __future__ import annotations

"""Max-hold lifecycle for XAU V24 champion DEMO positions."""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_structural_profit_protector import (
    _close_full_position,
    _raw_volume_by_position,
    _signal_id_from_comment,
)
from .demo_xau_v24_champion_candidate_producer import (
    D1_COMPONENT,
    L12_COMPONENT,
    L20_COMPONENT,
    STRATEGY_ID,
)
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_xau_v24_champion_time_exit"
_COMPONENT_CONTRACTS = {
    D1_COMPONENT: ("D1", 86400, 30),
    L12_COMPONENT: ("M15", 900, 16),
    L20_COMPONENT: ("M15", 900, 16),
}


def _geometry(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
) -> dict[str, Any] | None:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("code,payload,event_type,observed_at")
            .eq("signal_key", str(signal_id))
            .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
            .eq("code", STRATEGY_ID)
            .order("observed_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    rows = list(response.data or [])
    if len(rows) != 1:
        return None
    payload = dict(rows[0].get("payload") or {})
    component = str(payload.get("component_id") or "")
    if component not in _COMPONENT_CONTRACTS:
        return None
    return payload


def _closed_bars_since_open(
    session,
    *,
    timeframe: str,
    timeframe_seconds: int,
    max_hold_bars: int,
    opened_at: datetime,
    now: datetime,
) -> int:
    factor = 1.70 if timeframe == "D1" else 1.30
    start = opened_at.astimezone(UTC) - timedelta(
        seconds=timeframe_seconds * (max_hold_bars + 24) * factor
    )
    fetched = tuple(
        session.historical_bars(
            "XAUUSD",
            timeframe,
            from_time=start,
            to_time=now,
            count=max_hold_bars + 40,
        )
    )
    closed = _closed_bars(
        fetched,
        as_of=now,
        timeframe_seconds=timeframe_seconds,
    )
    return sum(
        1
        for row in closed
        if ensure_utc(row.timestamp) + timedelta(seconds=timeframe_seconds)
        > opened_at.astimezone(UTC)
    )


def _completed_utc_d1_bars_since_open(
    session,
    *,
    opened_at: datetime,
    now: datetime,
) -> int:
    """Count completed UTC-calendar trading days from H1, matching V20/V24 D1."""
    opened = ensure_utc(opened_at)
    current = ensure_utc(now)
    start = datetime.combine(opened.date(), datetime.min.time(), tzinfo=UTC)
    if current <= start:
        return 0
    rows = tuple(
        session.historical_bars(
            "XAUUSD",
            "H1",
            from_time=start,
            to_time=current,
            count=1600,
        )
    )
    completed_days = {
        ensure_utc(row.timestamp).date()
        for row in rows
        if opened.date() <= ensure_utc(row.timestamp).date() < current.date()
    }
    return len(completed_days)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(UTC)


def run() -> int:
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V24_TIME_EXIT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V24_TIME_EXIT_REQUIRE_DEMO")

    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("XAU_V24_TIME_EXIT_KILL_SWITCH_BLOCK")

    cfg = load_project_config(None)
    symbols = [pair.symbol for pair in cfg.pairs]
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))

    evaluated = eligible = closed_count = 0
    decisions: list[dict[str, Any]] = []
    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("XAU_V24_TIME_EXIT_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(
            session=session,
            store=None,
            phase="XAU_V24_CHAMPION_TIME_EXIT",
        )
        raw_volumes = _raw_volume_by_position(session)
        now = datetime.now(tz=UTC)

        for position in snapshot.positions:
            if str(position.symbol).upper() != "XAUUSD":
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None:
                continue
            geometry = _geometry(store, signal_id=signal_id)
            if geometry is None:
                continue
            component = str(geometry["component_id"])
            timeframe, timeframe_seconds, max_hold = _COMPONENT_CONTRACTS[component]
            evaluated += 1

            if position.opened_at is None:
                decisions.append(
                    {
                        "position_id": str(position.position_id),
                        "signal_id": signal_id,
                        "component_id": component,
                        "reason": "OPENED_AT_UNAVAILABLE",
                    }
                )
                continue

            if component == D1_COMPONENT:
                closed_bars = _completed_utc_d1_bars_since_open(
                    session,
                    opened_at=position.opened_at,
                    now=now,
                )
            else:
                closed_bars = _closed_bars_since_open(
                    session,
                    timeframe=timeframe,
                    timeframe_seconds=timeframe_seconds,
                    max_hold_bars=max_hold,
                    opened_at=position.opened_at,
                    now=now,
                )
            decision = {
                "position_id": str(position.position_id),
                "signal_id": signal_id,
                "component_id": component,
                "strategy_id": STRATEGY_ID,
                "timeframe": timeframe,
                "closed_bars": closed_bars,
                "max_hold_bars": max_hold,
                "reason": "HOLD" if closed_bars < max_hold else "MAX_HOLD_REACHED",
            }
            decisions.append(decision)
            if closed_bars < max_hold:
                continue

            raw_volume = int(raw_volumes.get(int(position.position_id), 0) or 0)
            if raw_volume <= 0:
                decision["execution"] = "RAW_VOLUME_UNAVAILABLE"
                continue
            eligible += 1
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                broker_order_id=f"V24_TIME_EXIT_REQUEST:{position.position_id}",
                event_type="DEMO_XAU_V24_TIME_EXIT_REQUEST",
                accepted=None,
                code=component,
                message=f"{timeframe} max-hold close requested",
                payload=decision,
            )
            status, detail = _close_full_position(
                session,
                position_id=int(position.position_id),
                raw_volume=raw_volume,
            )
            decision["execution"] = status
            decision["execution_detail"] = detail
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                broker_order_id=f"V24_TIME_EXIT:{position.position_id}",
                event_type="DEMO_XAU_V24_TIME_EXIT_RESULT",
                accepted=True if status == "CLOSED" else False if status == "REJECTED" else None,
                code=status,
                message=f"{timeframe} max-hold close result",
                payload=decision,
            )
            if status == "CLOSED":
                closed_count += 1

        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "strategy_id": STRATEGY_ID,
                "components": {
                    key: {
                        "timeframe": value[0],
                        "max_hold_bars": value[2],
                    }
                    for key, value in _COMPONENT_CONTRACTS.items()
                },
                "evaluated": evaluated,
                "eligible": eligible,
                "closed": closed_count,
                "decisions": decisions[-30:],
                "live_execution_enabled": False,
            },
        )
        print(
            "CTRADER_DEMO_XAU_V24_TIME_EXIT "
            f"evaluated={evaluated} eligible={eligible} closed={closed_count}"
        )
        return 0
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())

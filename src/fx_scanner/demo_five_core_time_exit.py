from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_five_core_router import D1_MAX_HOLD_BARS, PAIR_STRATEGY_IDS
from .demo_market_schedule import apply_demo_market_schedule
from .demo_structural_profit_protector import (
    _close_full_position,
    _raw_volume_by_position,
    _signal_id_from_comment,
)
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_five_core_time_exit"
TARGET_STRATEGY = PAIR_STRATEGY_IDS["XAUUSD"]


def _strategy_id_for_signal(store: SupabaseOperationalStore, signal_id: str) -> str | None:
    try:
        response = (
            store.client.table("broker_order_events")
            .select("code")
            .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
            .eq("signal_key", str(signal_id))
            .order("observed_at", desc=True)
            .limit(2)
            .execute()
        )
    except Exception:
        return None
    rows = list(response.data or [])
    if len(rows) != 1:
        return None
    return str(rows[0].get("code") or "") or None


def _closed_d1_bars_since_open(session, *, symbol: str, opened_at: datetime, now: datetime) -> int:
    start = opened_at.astimezone(UTC) - timedelta(days=3)
    fetched = tuple(
        session.historical_bars(
            symbol,
            "D1",
            from_time=start,
            to_time=now,
            count=D1_MAX_HOLD_BARS + 12,
        )
    )
    closed = _closed_bars(
        fetched,
        as_of=now,
        timeframe_seconds=86400,
    )
    return sum(
        1
        for row in closed
        if row.timestamp + timedelta(seconds=86400) > opened_at.astimezone(UTC)
    )


def run() -> int:
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("FIVE_CORE_TIME_EXIT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("FIVE_CORE_TIME_EXIT_REQUIRE_DEMO")

    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("FIVE_CORE_TIME_EXIT_KILL_SWITCH_BLOCK")

    cfg = load_project_config(None)
    _cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    all_symbols = [pair.symbol for pair in load_project_config(None).pairs]
    _gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    evaluated = eligible = closed_count = 0
    decisions: list[dict[str, Any]] = []

    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("FIVE_CORE_TIME_EXIT_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="FIVE_CORE_TIME_EXIT")
        raw_volumes = _raw_volume_by_position(session)
        now = datetime.now(tz=UTC)

        for position in snapshot.positions:
            symbol = str(position.symbol).upper()
            if symbol != "XAUUSD":
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None:
                continue
            strategy_id = _strategy_id_for_signal(store, signal_id)
            if strategy_id != TARGET_STRATEGY:
                continue
            evaluated += 1
            opened_at = position.opened_at
            if opened_at is None:
                decisions.append({
                    "position_id": str(position.position_id),
                    "signal_id": signal_id,
                    "reason": "OPENED_AT_UNAVAILABLE",
                })
                continue

            closed_bars = _closed_d1_bars_since_open(
                session,
                symbol=symbol,
                opened_at=opened_at,
                now=now,
            )
            decision = {
                "position_id": str(position.position_id),
                "signal_id": signal_id,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "closed_d1_bars": closed_bars,
                "max_hold_bars": D1_MAX_HOLD_BARS,
                "reason": "HOLD" if closed_bars < D1_MAX_HOLD_BARS else "MAX_HOLD_REACHED",
            }
            decisions.append(decision)
            if closed_bars < D1_MAX_HOLD_BARS:
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
                broker_order_id=f"TIME_EXIT_REQUEST:{position.position_id}",
                event_type="DEMO_FIVE_CORE_TIME_EXIT_REQUEST",
                accepted=None,
                code=TARGET_STRATEGY,
                message="D1 max-hold close requested",
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
                broker_order_id=f"TIME_EXIT:{position.position_id}",
                event_type="DEMO_FIVE_CORE_TIME_EXIT_RESULT",
                accepted=True if status == "CLOSED" else False if status == "REJECTED" else None,
                code=status,
                message="D1 max-hold close result",
                payload=decision,
            )
            if status == "CLOSED":
                closed_count += 1

        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "strategy_id": TARGET_STRATEGY,
                "evaluated": evaluated,
                "eligible": eligible,
                "closed": closed_count,
                "market_schedule_mode": market_schedule_mode,
                "decisions": decisions[-20:],
            },
        )
        print(
            "CTRADER_DEMO_FIVE_CORE_TIME_EXIT_OK "
            f"evaluated={evaluated} eligible={eligible} closed={closed_count}"
        )
        return 0
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_five_core_time_exit import _strategy_id_for_signal
from .demo_market_schedule import apply_demo_market_schedule
from .demo_structural_profit_protector import _close_full_position, _raw_volume_by_position, _signal_id_from_comment
from .demo_xau_expansion_v42 import MAX_HOLD_D1_BARS, STRATEGY_ID
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_xau_expansion_v42_time_exit"


def _closed_d1_bars_since_open(session, *, opened_at: datetime, now: datetime) -> int:
    fetched = tuple(
        session.historical_bars(
            "XAUUSD",
            "D1",
            from_time=opened_at.astimezone(UTC) - timedelta(days=3),
            to_time=now,
            count=MAX_HOLD_D1_BARS + 12,
        )
    )
    closed = _closed_bars(fetched, as_of=now, timeframe_seconds=86400)
    return sum(1 for row in closed if row.timestamp + timedelta(days=1) > opened_at.astimezone(UTC))


def run() -> int:
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_EXPANSION_V42_TIME_EXIT_DEMO_ONLY")
    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("XAU_EXPANSION_V42_TIME_EXIT_KILL_SWITCH_BLOCK")

    cfg, market_schedule_mode = apply_demo_market_schedule(load_project_config(None))
    all_symbols = [pair.symbol for pair in load_project_config(None).pairs]
    _gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    evaluated = eligible = closed_count = 0
    decisions: list[dict[str, Any]] = []
    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("XAU_EXPANSION_V42_TIME_EXIT_CONTROL_PLANE_BLOCK")
        snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="XAU_V42_TIME_EXIT")
        raw_volumes = _raw_volume_by_position(session)
        now = datetime.now(tz=UTC)
        for position in snapshot.positions:
            if str(position.symbol).upper() != "XAUUSD":
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None or _strategy_id_for_signal(store, signal_id) != STRATEGY_ID:
                continue
            evaluated += 1
            if position.opened_at is None:
                decisions.append({"position_id": str(position.position_id), "signal_id": signal_id, "reason": "OPENED_AT_UNAVAILABLE"})
                continue
            closed_bars = _closed_d1_bars_since_open(session, opened_at=position.opened_at, now=now)
            decision = {
                "position_id": str(position.position_id),
                "signal_id": signal_id,
                "strategy_id": STRATEGY_ID,
                "closed_d1_bars": closed_bars,
                "max_hold_bars": MAX_HOLD_D1_BARS,
                "reason": "HOLD" if closed_bars < MAX_HOLD_D1_BARS else "MAX_HOLD_REACHED",
            }
            decisions.append(decision)
            if closed_bars < MAX_HOLD_D1_BARS:
                continue
            raw_volume = int(raw_volumes.get(int(position.position_id), 0) or 0)
            if raw_volume <= 0:
                decision["execution"] = "RAW_VOLUME_UNAVAILABLE"
                continue
            eligible += 1
            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    broker_order_id=f"XAU_V42_TIME_EXIT_REQUEST:{position.position_id}",
                    event_type="DEMO_XAU_EXPANSION_V42_TIME_EXIT_REQUEST",
                    accepted=None,
                    code=STRATEGY_ID,
                    message="V4.2 D1 seven-bar max-hold close requested",
                    payload=decision,
                )
            except Exception as exc:
                decision["execution"] = f"AUDIT_PERSIST_FAILED:{type(exc).__name__}"
                continue
            status, detail = _close_full_position(session, position_id=int(position.position_id), raw_volume=raw_volume)
            decision["execution"] = status
            decision["execution_detail"] = detail
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                broker_order_id=f"XAU_V42_TIME_EXIT:{position.position_id}",
                event_type="DEMO_XAU_EXPANSION_V42_TIME_EXIT_RESULT",
                accepted=True if status == "CLOSED" else False if status == "REJECTED" else None,
                code=status,
                message="V4.2 D1 seven-bar max-hold close result",
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
                "evaluated": evaluated,
                "eligible": eligible,
                "closed": closed_count,
                "max_hold_bars": MAX_HOLD_D1_BARS,
                "market_schedule_mode": market_schedule_mode,
                "decisions": decisions[-20:],
            },
        )
        print(f"CTRADER_DEMO_XAU_EXPANSION_V42_TIME_EXIT_OK evaluated={evaluated} eligible={eligible} closed={closed_count}")
        return 0
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())

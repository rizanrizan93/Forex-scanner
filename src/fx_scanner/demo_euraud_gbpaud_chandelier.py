from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any
from uuid import uuid4

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_adaptive_profit_lock import _amend_once, normalize_profit_lock_stop
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_euraud_gbpaud_forward_evidence import (
    EURAUD_STRATEGY_ID,
    GBPAUD_STRATEGY_ID,
    PAIR_SPECS,
)
from .demo_five_core_router import _true_ranges, _wilder_ewm
from .demo_five_core_time_exit import _strategy_id_for_signal
from .demo_market_schedule import apply_demo_market_schedule
from .demo_structural_profit_protector import _signal_id_from_comment, _signal_matches_position
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_euraud_gbpaud_chandelier"
STRATEGY_BY_SYMBOL = {
    "EURAUD": EURAUD_STRATEGY_ID,
    "GBPAUD": GBPAUD_STRATEGY_ID,
}
TRAIL_ATR_BY_SYMBOL = {
    symbol: float(PAIR_SPECS[symbol]["trail_atr"])
    for symbol in STRATEGY_BY_SYMBOL
}


def _closed_d1_since_open(session, *, symbol: str, opened_at: datetime, now: datetime):
    start = opened_at.astimezone(UTC) - timedelta(days=45)
    fetched = tuple(
        session.historical_bars(
            symbol,
            "D1",
            from_time=start,
            to_time=now,
            count=220,
        )
    )
    closed = _closed_bars(fetched, as_of=now, timeframe_seconds=86400)
    if len(closed) < 20:
        return (), closed
    since_open = tuple(
        row
        for row in closed
        if row.timestamp + timedelta(seconds=86400) > opened_at.astimezone(UTC)
    )
    return since_open, closed


def _chandelier_target(
    *,
    side: str,
    since_open,
    atr14: float,
    trail_atr: float,
) -> float | None:
    if not since_open or not isfinite(atr14) or atr14 <= 0:
        return None
    if side == "BUY":
        return max(float(row.high) for row in since_open) - trail_atr * atr14
    if side == "SELL":
        return min(float(row.low) for row in since_open) + trail_atr * atr14
    return None


def run() -> int:
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if (
        str(policy.ctrader.get("environment", "")).upper() != "DEMO"
        or not bool(policy.ctrader.get("require_demo", False))
    ):
        raise SystemExit("EURAUD_GBPAUD_CHANDELIER_DEMO_ONLY")

    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("EURAUD_GBPAUD_CHANDELIER_KILL_SWITCH_BLOCK")

    cfg, market_schedule_mode = apply_demo_market_schedule(load_project_config(None))
    all_symbols = [pair.symbol for pair in load_project_config(None).pairs]
    _gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    evaluated = amended = rejected = uncertain = 0
    decisions: list[dict[str, Any]] = []

    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("EURAUD_GBPAUD_CHANDELIER_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(
            session=session, store=None, phase="EURAUD_GBPAUD_CHANDELIER"
        )
        now = datetime.now(tz=UTC)
        for position in snapshot.positions:
            symbol = str(position.symbol).upper()
            expected_strategy = STRATEGY_BY_SYMBOL.get(symbol)
            if expected_strategy is None:
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None:
                continue
            if not _signal_matches_position(
                store,
                signal_id=signal_id,
                symbol=symbol,
                side=position.side,
            ):
                continue
            strategy_id = _strategy_id_for_signal(store, signal_id)
            if strategy_id != expected_strategy:
                continue
            evaluated += 1

            if (
                position.opened_at is None
                or position.stop_loss is None
                or position.take_profit is None
                or position.current_price is None
            ):
                decisions.append(
                    {
                        "position_id": str(position.position_id),
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "reason": "BROKER_GEOMETRY_OR_OPEN_TIME_INCOMPLETE",
                    }
                )
                continue

            since_open, closed = _closed_d1_since_open(
                session,
                symbol=symbol,
                opened_at=position.opened_at,
                now=now,
            )
            if len(closed) < 14 or not since_open:
                decisions.append(
                    {
                        "position_id": str(position.position_id),
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "reason": "NO_COMPLETED_POST_ENTRY_D1_BAR",
                    }
                )
                continue
            atr14 = float(_wilder_ewm(_true_ranges(closed), 14)[-1])
            trail_atr = TRAIL_ATR_BY_SYMBOL[symbol]
            side = str(position.side).upper()
            current_stop = float(position.stop_loss)
            target = _chandelier_target(
                side=side,
                since_open=since_open,
                atr14=atr14,
                trail_atr=trail_atr,
            )
            reason = "NO_CHANDELIER_TARGET"
            if target is not None:
                if side == "BUY" and target > current_stop:
                    reason = "TIGHTEN_LONG_CHANDELIER"
                elif side == "SELL" and target < current_stop:
                    reason = "TIGHTEN_SHORT_CHANDELIER"
                else:
                    reason = "NO_MONOTONIC_IMPROVEMENT"

            payload = {
                "position_id": str(position.position_id),
                "signal_id": signal_id,
                "symbol": symbol,
                "strategy_id": strategy_id,
                "side": side,
                "current_stop": current_stop,
                "take_profit": float(position.take_profit),
                "current_price": float(position.current_price),
                "closed_post_entry_d1_bars": len(since_open),
                "atr14": atr14,
                "trail_atr": trail_atr,
                "raw_chandelier_stop": target,
                "decision": reason,
                "tp_mutated": False,
                "entry_mutated": False,
            }
            decisions.append(payload)
            if reason not in {"TIGHTEN_LONG_CHANDELIER", "TIGHTEN_SHORT_CHANDELIER"}:
                continue

            normalized_stop, normalization = normalize_profit_lock_stop(
                session,
                symbol=symbol,
                side=side,
                target_stop=float(target),
                current_stop=current_stop,
                current_price=float(position.current_price),
            )
            if normalized_stop is None:
                decisions[-1]["execution"] = "FAIL_CLOSED"
                decisions[-1]["execution_detail"] = normalization
                continue
            payload["normalized_chandelier_stop"] = normalized_stop
            payload["price_normalization"] = normalization
            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_EURAUD_GBPAUD_CHANDELIER_REQUEST",
                    broker_order_id=(
                        f"CROSS_CHANDELIER_REQUEST:{position.position_id}:{uuid4().hex[:8]}"
                    ),
                    accepted=None,
                    code=strategy_id,
                    message="frozen D1 Chandelier stop advance requested",
                    payload=payload,
                )
            except Exception:
                decisions[-1]["execution"] = "AUDIT_PERSIST_FAILED"
                continue

            status, detail = _amend_once(
                session,
                position_id=int(position.position_id),
                stop_loss=float(normalized_stop),
                take_profit=float(position.take_profit),
            )
            decisions[-1]["execution"] = status
            decisions[-1]["execution_detail"] = detail
            if status == "ACKNOWLEDGED":
                amended += 1
            elif status == "REJECTED":
                rejected += 1
            else:
                uncertain += 1
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                event_type="DEMO_EURAUD_GBPAUD_CHANDELIER_RESULT",
                broker_order_id=f"CROSS_CHANDELIER:{position.position_id}:{uuid4().hex[:8]}",
                accepted=True if status == "ACKNOWLEDGED" else False if status == "REJECTED" else None,
                code=status,
                message="frozen D1 Chandelier stop advance result",
                payload=payload,
            )

        store.write_heartbeat(
            WORKER_NAME,
            healthy=uncertain == 0,
            lag_seconds=0.0,
            details={
                "environment": "DEMO",
                "live_execution_enabled": False,
                "strategies": STRATEGY_BY_SYMBOL,
                "trail_atr": TRAIL_ATR_BY_SYMBOL,
                "market_schedule_mode": market_schedule_mode,
                "evaluated": evaluated,
                "amended": amended,
                "rejected": rejected,
                "uncertain": uncertain,
                "decisions": decisions[-40:],
            },
        )
        print(
            "CTRADER_DEMO_EURAUD_GBPAUD_CHANDELIER_OK "
            f"evaluated={evaluated} amended={amended} rejected={rejected} uncertain={uncertain}"
        )
        return 0 if uncertain == 0 else 2
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())

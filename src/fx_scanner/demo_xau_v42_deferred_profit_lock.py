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
from .demo_five_core_time_exit import _strategy_id_for_signal
from .demo_market_schedule import apply_demo_market_schedule
from .demo_structural_profit_protector import _signal_id_from_comment, _signal_matches_position
from .demo_xau_expansion_v42 import STRATEGY_ID
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
FEATURE_ENV = "CTRADER_DEMO_XAU_V42_PROFIT_LOCK_ENABLED"
STATE_WORKER = "ctrader_demo_xau_v42_deferred_profit_lock"


def deferred_lock_r(favorable_r: float) -> float | None:
    if favorable_r < 1.25:
        return None
    if favorable_r < 1.75:
        return 0.10
    if favorable_r < 2.25:
        return 0.50
    if favorable_r < 2.50:
        return 1.00
    return max(1.00, favorable_r - 1.00)


def _load_state(store: SupabaseOperationalStore) -> dict[str, Any]:
    try:
        response = (
            store.client.table("runtime_heartbeats")
            .select("details")
            .eq("worker_name", STATE_WORKER)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
    except Exception:
        return {"positions": {}, "uncertain_position_ids": []}
    if not rows or not isinstance(rows[0].get("details"), dict):
        return {"positions": {}, "uncertain_position_ids": []}
    details = dict(rows[0]["details"])
    details["positions"] = dict(details.get("positions") or {})
    details["uncertain_position_ids"] = list(details.get("uncertain_position_ids") or [])
    return details


def _latest_closed_h1(session, *, now: datetime) -> tuple[datetime, float] | None:
    fetched = tuple(
        session.historical_bars(
            "XAUUSD",
            "H1",
            from_time=now - timedelta(days=5),
            to_time=now,
            count=100,
        )
    )
    closed = _closed_bars(fetched, as_of=now, timeframe_seconds=3600)
    if not closed:
        return None
    row = closed[-1]
    return row.timestamp, float(row.close)


def _decision(
    *,
    side: str,
    entry: float,
    original_stop: float,
    current_stop: float,
    h1_close: float,
) -> tuple[float | None, float | None, str]:
    side = str(side).upper()
    if not all(isfinite(float(x)) and float(x) > 0 for x in (entry, original_stop, current_stop, h1_close)):
        return None, None, "PRICE_INVALID"
    risk = entry - original_stop if side == "BUY" else original_stop - entry
    if side not in {"BUY", "SELL"} or risk <= 0:
        return None, None, "ORIGINAL_RISK_INVALID"
    favorable = (h1_close - entry) / risk if side == "BUY" else (entry - h1_close) / risk
    lock = deferred_lock_r(favorable)
    if lock is None:
        return favorable, None, "BELOW_DEFERRED_ACTIVATION"
    target = entry + lock * risk if side == "BUY" else entry - lock * risk
    epsilon = max(abs(entry), 1.0) * 1e-10
    if side == "BUY" and target <= current_stop + epsilon:
        return favorable, lock, "NO_MONOTONIC_IMPROVEMENT"
    if side == "SELL" and target >= current_stop - epsilon:
        return favorable, lock, "NO_MONOTONIC_IMPROVEMENT"
    return favorable, lock, "DEFERRED_STEP_ADVANCE"


def run() -> int:
    if os.getenv(FEATURE_ENV, "0").strip() != "1":
        print("CTRADER_DEMO_XAU_V42_PROFIT_LOCK_DISABLED")
        return 0
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V42_PROFIT_LOCK_DEMO_ONLY")
    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("XAU_V42_PROFIT_LOCK_KILL_SWITCH_BLOCK")

    cfg, market_schedule_mode = apply_demo_market_schedule(load_project_config(None))
    active_symbols = {pair.symbol for pair in cfg.pairs}
    all_symbols = [pair.symbol for pair in load_project_config(None).pairs]
    _gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    state = _load_state(store)
    positions_state = dict(state.get("positions") or {})
    uncertain = {str(x) for x in state.get("uncertain_position_ids", [])}
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    decisions: list[dict[str, Any]] = []
    evaluated = amended = rejected = quarantined = 0
    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("XAU_V42_PROFIT_LOCK_CONTROL_PLANE_BLOCK")
        snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="XAU_V42_PROFIT_LOCK")
        now = datetime.now(tz=UTC)
        h1 = _latest_closed_h1(session, now=now)
        if h1 is None:
            raise SystemExit("XAU_V42_PROFIT_LOCK_H1_UNAVAILABLE")
        h1_at, h1_close = h1
        open_ids = {str(position.position_id) for position in snapshot.positions}
        for position in snapshot.positions:
            position_id = str(position.position_id)
            symbol = str(position.symbol).upper()
            if symbol != "XAUUSD" or symbol not in active_symbols:
                continue
            if position_id in uncertain:
                quarantined += 1
                decisions.append({"position_id": position_id, "reason": "UNCERTAIN_OUTCOME_QUARANTINE"})
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None or not _signal_matches_position(store, signal_id=signal_id, symbol=symbol, side=position.side):
                continue
            if _strategy_id_for_signal(store, signal_id) != STRATEGY_ID:
                continue
            evaluated += 1
            if position.stop_loss is None or position.take_profit is None or position.current_price is None:
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "BROKER_GEOMETRY_INCOMPLETE"})
                continue

            item = dict(positions_state.get(position_id) or {})
            entry = float(position.open_price)
            current_stop = float(position.stop_loss)
            side = str(position.side).upper()
            original_stop = item.get("original_stop")
            if original_stop is None:
                valid = (side == "BUY" and current_stop < entry) or (side == "SELL" and current_stop > entry)
                if not valid:
                    decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "ORIGINAL_RISK_UNKNOWN_FAIL_CLOSED"})
                    continue
                original_stop = current_stop
                item.update({
                    "position_id": position_id,
                    "signal_id": signal_id,
                    "strategy_id": STRATEGY_ID,
                    "side": side,
                    "entry_price": entry,
                    "original_stop": float(original_stop),
                    "captured_at": now.isoformat(),
                })
                positions_state[position_id] = item

            favorable_r, lock_r, reason = _decision(
                side=side,
                entry=entry,
                original_stop=float(original_stop),
                current_stop=current_stop,
                h1_close=h1_close,
            )
            target_stop = None if lock_r is None else (entry + lock_r * (entry - float(original_stop)) if side == "BUY" else entry - lock_r * (float(original_stop) - entry))
            payload = {
                "position_id": position_id,
                "signal_id": signal_id,
                "strategy_id": STRATEGY_ID,
                "side": side,
                "entry_price": entry,
                "original_stop": float(original_stop),
                "current_stop": current_stop,
                "take_profit": float(position.take_profit),
                "current_price": float(position.current_price),
                "decision_h1_at": h1_at.isoformat(),
                "decision_h1_close": h1_close,
                "favorable_r": favorable_r,
                "lock_r": lock_r,
                "target_stop": target_stop,
                "decision": reason,
                "policy": "DEFERRED_STEP_V42",
                "tp_mutated": False,
                "entry_mutated": False,
            }
            decisions.append(payload)
            if reason != "DEFERRED_STEP_ADVANCE" or target_stop is None:
                continue
            normalized_stop, normalization = normalize_profit_lock_stop(
                session,
                symbol=symbol,
                side=side,
                target_stop=float(target_stop),
                current_stop=current_stop,
                current_price=float(position.current_price),
            )
            if normalized_stop is None:
                decisions[-1]["execution"] = "FAIL_CLOSED"
                decisions[-1]["execution_detail"] = normalization
                continue
            payload["target_stop"] = normalized_stop
            payload["price_normalization"] = normalization
            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_XAU_V42_DEFERRED_PROFIT_LOCK_REQUEST",
                    broker_order_id=f"XAU_V42_LOCK_REQUEST:{position_id}:{uuid4().hex[:8]}",
                    accepted=None,
                    code="DEFERRED_STEP_ADVANCE",
                    message="V4.2 completed-H1 deferred stop advance requested",
                    payload=payload,
                )
            except Exception:
                decisions[-1]["execution"] = "AUDIT_PERSIST_FAILED"
                continue
            status, detail = _amend_once(
                session,
                position_id=int(position_id),
                stop_loss=normalized_stop,
                take_profit=float(position.take_profit),
            )
            decisions[-1]["execution"] = status
            decisions[-1]["execution_detail"] = detail
            if status == "ACKNOWLEDGED":
                amended += 1
                item["last_target_stop"] = normalized_stop
                item["last_lock_r"] = lock_r
                item["last_decision_h1_at"] = h1_at.isoformat()
                item["last_amended_at"] = now.isoformat()
                positions_state[position_id] = item
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_XAU_V42_DEFERRED_PROFIT_LOCK_ADVANCED",
                    broker_order_id=f"XAU_V42_LOCK:{position_id}:{uuid4().hex[:8]}",
                    accepted=True,
                    code="SL_ADVANCED",
                    message="V4.2 server-side SL advanced; TP unchanged",
                    payload=payload,
                )
            elif status == "REJECTED":
                rejected += 1
            else:
                quarantined += 1
                uncertain.add(position_id)
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_XAU_V42_DEFERRED_PROFIT_LOCK_UNCERTAIN",
                    broker_order_id=f"XAU_V42_LOCK_UNCERTAIN:{position_id}",
                    accepted=None,
                    code="OUTCOME_UNCERTAIN",
                    message=detail[:500],
                    payload=payload,
                )

        positions_state = {key: value for key, value in positions_state.items() if key in open_ids}
        state = {
            "version": 1,
            "mode": "DEMO_ONLY",
            "strategy_id": STRATEGY_ID,
            "policy": "DEFERRED_STEP_V42",
            "market_schedule_mode": market_schedule_mode,
            "positions": dict(list(positions_state.items())[-128:]),
            "uncertain_position_ids": sorted(uncertain),
            "activation_r": 1.25,
            "stages": {"1.25": 0.10, "1.75": 0.50, "2.25": 1.00, "2.50+": "TRAIL_1.00R"},
            "evaluated": evaluated,
            "amended": amended,
            "rejected": rejected,
            "quarantined": quarantined,
            "decisions": decisions[-50:],
        }
        store.write_heartbeat(STATE_WORKER, healthy=True, lag_seconds=0.0, details=state)
        print(f"CTRADER_DEMO_XAU_V42_PROFIT_LOCK_OK evaluated={evaluated} amended={amended} rejected={rejected} quarantined={quarantined}")
        return 0
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(run())

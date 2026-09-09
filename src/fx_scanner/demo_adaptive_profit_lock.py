from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from uuid import uuid4

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_market_schedule import apply_demo_market_schedule
from .demo_structural_profit_protector import _signal_id_from_comment, _signal_matches_position
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
FEATURE_ENV = "CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_ENABLED"
STATE_WORKER = "ctrader_demo_adaptive_profit_lock"


@dataclass(frozen=True, slots=True)
class ProfitLockDecision:
    amend: bool
    reason: str
    favorable_r: float | None
    lock_r: float | None
    target_stop: float | None


def evaluate_profit_lock(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    current_stop: float,
    original_stop: float,
) -> ProfitLockDecision:
    """Return a monotonic DEMO-only profit-lock decision using price-R geometry.

    The original broker entry-to-SL distance is captured once and persisted.
    This is runtime price geometry only; it is not MAE_R/MFE_R calibration.
    TP and entry are never changed here.
    """
    side = str(side).upper()
    values = (entry_price, current_price, current_stop, original_stop)
    try:
        entry, current, stop, original = (float(value) for value in values)
    except (TypeError, ValueError):
        return ProfitLockDecision(False, "PRICE_INVALID", None, None, None)
    if side not in {"BUY", "SELL"} or not all(isfinite(v) and v > 0 for v in (entry, current, stop, original)):
        return ProfitLockDecision(False, "PRICE_INVALID", None, None, None)

    if side == "BUY":
        risk = entry - original
        excursion = current - entry
    else:
        risk = original - entry
        excursion = entry - current
    if risk <= 0:
        return ProfitLockDecision(False, "ORIGINAL_RISK_INVALID", None, None, None)

    favorable_r = excursion / risk
    if favorable_r < 0.50:
        return ProfitLockDecision(False, "BELOW_ACTIVATION", favorable_r, None, None)
    if favorable_r < 0.80:
        lock_r = 0.05
    elif favorable_r < 1.20:
        lock_r = 0.25
    elif favorable_r < 1.80:
        lock_r = 0.55
    elif favorable_r < 2.50:
        lock_r = 1.00
    else:
        lock_r = max(1.00, favorable_r - 0.75)

    target = entry + lock_r * risk if side == "BUY" else entry - lock_r * risk
    epsilon = max(abs(entry), 1.0) * 1e-10
    if side == "BUY":
        if target <= stop + epsilon:
            return ProfitLockDecision(False, "NO_MONOTONIC_IMPROVEMENT", favorable_r, lock_r, target)
        if target >= current - epsilon:
            return ProfitLockDecision(False, "TARGET_NOT_BEHIND_MARKET", favorable_r, lock_r, target)
    else:
        if target >= stop - epsilon:
            return ProfitLockDecision(False, "NO_MONOTONIC_IMPROVEMENT", favorable_r, lock_r, target)
        if target <= current + epsilon:
            return ProfitLockDecision(False, "TARGET_NOT_BEHIND_MARKET", favorable_r, lock_r, target)
    return ProfitLockDecision(True, "PROFIT_LOCK_ADVANCE", favorable_r, lock_r, target)


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


def _symbol_digits(session, symbol: str) -> int | None:
    """Return cTrader price digits, failing closed when precision is unavailable."""
    try:
        info = session.symbol_info(str(symbol).upper())
    except Exception:
        return None
    raw_digits = getattr(info, "digits", None)
    if raw_digits is not None:
        try:
            digits = int(raw_digits)
        except (TypeError, ValueError):
            digits = -1
        if 0 <= digits <= 10:
            return digits
    raw_pip_position = getattr(info, "pipPosition", None)
    if raw_pip_position is not None:
        try:
            digits = int(raw_pip_position) + 1
        except (TypeError, ValueError):
            digits = -1
        if 0 <= digits <= 10:
            return digits
    return None


def normalize_profit_lock_stop(
    session,
    *,
    symbol: str,
    side: str,
    target_stop: float,
    current_stop: float,
    current_price: float,
) -> tuple[float | None, str]:
    """Round a proposed SL to broker precision and revalidate monotonic geometry."""
    digits = _symbol_digits(session, symbol)
    if digits is None:
        return None, "BROKER_PRICE_PRECISION_UNKNOWN_FAIL_CLOSED"
    try:
        target = round(float(target_stop), digits)
        stop = float(current_stop)
        market = float(current_price)
    except (TypeError, ValueError):
        return None, "BROKER_PRICE_NORMALIZATION_INVALID"
    if not all(isfinite(v) and v > 0 for v in (target, stop, market)):
        return None, "BROKER_PRICE_NORMALIZATION_INVALID"
    direction = str(side).upper()
    if direction == "BUY":
        if not stop < target < market:
            return None, "BROKER_ROUNDED_STOP_GEOMETRY_INVALID"
    elif direction == "SELL":
        if not market < target < stop:
            return None, "BROKER_ROUNDED_STOP_GEOMETRY_INVALID"
    else:
        return None, "BROKER_PRICE_NORMALIZATION_INVALID"
    return target, f"BROKER_PRICE_NORMALIZED_{digits}DP"


def _amend_once(session, *, position_id: int, stop_loss: float, take_profit: float) -> tuple[str, str]:
    """Submit one SL-only improvement. Ambiguous transport outcomes are quarantined."""
    try:
        helper = getattr(session, "send_amend_position_sltp", None)
        if callable(helper):
            helper(
                position_id=int(position_id),
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
                client_msg_id=f"profit-lock-{position_id}-{uuid4().hex[:8]}",
                timeout=5.0,
            )
        else:
            from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAAmendPositionSLTPReq

            req = ProtoOAAmendPositionSLTPReq()
            req.ctidTraderAccountId = int(session.account_id)
            req.positionId = int(position_id)
            req.stopLoss = float(stop_loss)
            req.takeProfit = float(take_profit)
            session._send_sync(
                req,
                client_msg_id=f"profit-lock-{position_id}-{uuid4().hex[:8]}",
                timeout=5.0,
            )
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        if "cTrader API error" in str(exc):
            return "REJECTED", text
        return "UNCERTAIN", text
    return "ACKNOWLEDGED", "AMEND_SUBMITTED_ONCE"


def run() -> int:
    if os.getenv(FEATURE_ENV, "0").strip() != "1":
        print("CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_DISABLED")
        return 0

    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_DEMO_ONLY")

    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_KILL_SWITCH_BLOCK")

    all_cfg = load_project_config(None)
    symbols = [pair.symbol for pair in all_cfg.pairs]
    active_symbols = {pair.symbol for pair in cfg.pairs}
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    state = _load_state(store)
    positions_state = dict(state.get("positions") or {})
    uncertain = {str(x) for x in state.get("uncertain_position_ids", [])}
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    decisions: list[dict[str, Any]] = []

    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="PROFIT_LOCK")
        open_ids = {str(position.position_id) for position in snapshot.positions}
        for position in snapshot.positions:
            position_id = str(position.position_id)
            symbol = str(position.symbol).upper()
            if symbol not in active_symbols or position_id in uncertain:
                continue
            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None or not _signal_matches_position(
                store, signal_id=signal_id, symbol=symbol, side=position.side
            ):
                continue
            if position.stop_loss is None or position.take_profit is None or position.current_price is None:
                decisions.append({"position_id": position_id, "symbol": symbol, "reason": "BROKER_GEOMETRY_INCOMPLETE"})
                continue

            item = dict(positions_state.get(position_id) or {})
            original_stop = item.get("original_stop")
            entry = float(position.open_price)
            current_stop = float(position.stop_loss)
            side = str(position.side).upper()
            if original_stop is None:
                valid_original = (side == "BUY" and current_stop < entry) or (side == "SELL" and current_stop > entry)
                if not valid_original:
                    decisions.append({"position_id": position_id, "symbol": symbol, "reason": "ORIGINAL_RISK_UNKNOWN_FAIL_CLOSED"})
                    continue
                original_stop = current_stop
                item.update(
                    {
                        "position_id": position_id,
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "side": side,
                        "entry_price": entry,
                        "original_stop": float(original_stop),
                        "captured_at": datetime.now(tz=UTC).isoformat(),
                    }
                )
                positions_state[position_id] = item

            decision = evaluate_profit_lock(
                side=side,
                entry_price=entry,
                current_price=float(position.current_price),
                current_stop=current_stop,
                original_stop=float(original_stop),
            )
            payload = {
                "position_id": position_id,
                "signal_id": signal_id,
                "symbol": symbol,
                "side": side,
                "entry_price": entry,
                "current_price": float(position.current_price),
                "current_stop": current_stop,
                "original_stop": float(original_stop),
                "take_profit": float(position.take_profit),
                "favorable_r": decision.favorable_r,
                "lock_r": decision.lock_r,
                "target_stop": decision.target_stop,
                "decision": decision.reason,
                "tp_mutated": False,
                "entry_mutated": False,
            }
            decisions.append(payload)
            if not decision.amend or decision.target_stop is None:
                continue

            normalized_stop, normalization = normalize_profit_lock_stop(
                session,
                symbol=symbol,
                side=side,
                target_stop=float(decision.target_stop),
                current_stop=current_stop,
                current_price=float(position.current_price),
            )
            if normalized_stop is None:
                decisions[-1]["execution"] = "FAIL_CLOSED"
                decisions[-1]["execution_detail"] = normalization
                continue
            payload["raw_target_stop"] = float(decision.target_stop)
            payload["target_stop"] = normalized_stop
            payload["price_normalization"] = normalization
            decisions[-1]["raw_target_stop"] = float(decision.target_stop)
            decisions[-1]["target_stop"] = normalized_stop
            decisions[-1]["price_normalization"] = normalization

            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_ADAPTIVE_PROFIT_LOCK_REQUEST",
                    broker_order_id=f"PROFIT_LOCK_REQUEST:{position_id}:{uuid4().hex[:8]}",
                    accepted=None,
                    code="PROFIT_LOCK_ADVANCE",
                    message="monotonic DEMO stop-loss profit lock requested",
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
                item["last_target_stop"] = normalized_stop
                item["last_lock_r"] = decision.lock_r
                item["last_amended_at"] = datetime.now(tz=UTC).isoformat()
                positions_state[position_id] = item
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_ADAPTIVE_PROFIT_LOCK_ADVANCED",
                    broker_order_id=f"PROFIT_LOCK:{position_id}:{uuid4().hex[:8]}",
                    accepted=True,
                    code="SL_ADVANCED",
                    message="server-side SL advanced; TP unchanged",
                    payload=payload,
                )
            elif status == "UNCERTAIN":
                uncertain.add(position_id)
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_ADAPTIVE_PROFIT_LOCK_UNCERTAIN",
                    broker_order_id=f"PROFIT_LOCK_UNCERTAIN:{position_id}",
                    accepted=None,
                    code="OUTCOME_UNCERTAIN",
                    message=detail[:500],
                    payload=payload,
                )

        ordered = list(positions_state.items())[-128:]
        state = {
            "version": 1,
            "mode": "DEMO_ONLY",
            "market_schedule_mode": market_schedule_mode,
            "positions": dict(ordered),
            "open_position_ids": sorted(open_ids),
            "uncertain_position_ids": sorted(uncertain),
            "activation_r": 0.50,
            "stages": {"0.50": 0.05, "0.80": 0.25, "1.20": 0.55, "1.80": 1.00, "2.50+": "TRAIL_0.75R"},
            "decisions": decisions[-50:],
        }
        store.write_heartbeat(STATE_WORKER, healthy=True, lag_seconds=0.0, details=state)
        print(
            "CTRADER_DEMO_ADAPTIVE_PROFIT_LOCK_OK "
            f"positions={len(snapshot.positions)} decisions={len(decisions)} uncertain={len(uncertain)}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
from dataclasses import asdict
from math import isfinite
from time import sleep
from typing import Any
from uuid import UUID, uuid4

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_structural_profit_protector import (
    _close_full_position,
    _fetch_structure,
    _raw_volume_by_position,
    evaluate_profit_protect,
)
from .demo_xau_m15_canonical_policy import PositionStage, evaluate_position_management
from .demo_xau_m15_ema_smc_reclaim import STRATEGY_ID, SYMBOL
from .execution.ctrader_protection import CTraderPostFillProtectionManager
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

STATE_WORKER = "ctrader_demo_xau_canonical_position_manager"
FEATURE_ENV = "CTRADER_DEMO_XAU_CANONICAL_POSITION_MANAGER_ENABLED"
STOP_BE_BUFFER_R = 0.03
TRAIL_SWING_BUFFER_R = 0.10
MIN_LIVE_STOP_DISTANCE_R = 0.30
VERIFY_ATTEMPTS = 5
VERIFY_POLL_SECONDS = 0.20


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive(value: Any) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0.0 else None


def _signal_id_from_comment(comment: str | None, prefix: str) -> str | None:
    text = str(comment or "").strip()
    marker = f"{str(prefix).strip()}:"
    if not text.startswith(marker):
        return None
    candidate = text[len(marker):].strip()
    try:
        return str(UUID(candidate))
    except (ValueError, TypeError, AttributeError):
        return None


def _load_canonical_signal_plan(store: SupabaseOperationalStore, *, signal_id: str) -> dict[str, Any] | None:
    try:
        signal_response = (
            store.client.table("signals")
            .select("id,symbol,direction,sl,tp1,tp2,observed_at")
            .eq("id", signal_id)
            .limit(2)
            .execute()
        )
        geometry_response = (
            store.client.table("broker_order_events")
            .select("signal_key,code,event_type")
            .eq("signal_key", signal_id)
            .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
            .order("observed_at", desc=True)
            .limit(4)
            .execute()
        )
    except Exception:
        return None

    signals = [dict(row) for row in (signal_response.data or [])]
    if len(signals) != 1:
        return None
    row = signals[0]
    if str(row.get("symbol") or "").upper() != SYMBOL:
        return None
    if str(row.get("direction") or "").upper() not in {"LONG", "SHORT"}:
        return None
    if _positive(row.get("sl")) is None or _positive(row.get("tp2")) is None:
        return None
    geometry_codes = {
        str(item.get("code") or "")
        for item in (geometry_response.data or [])
        if str(item.get("event_type") or "") == "DEMO_SIGNAL_GEOMETRY"
    }
    if STRATEGY_ID not in geometry_codes:
        return None
    return row


def _initial_risk_and_r(
    *,
    side: str,
    entry: float,
    planned_stop: float,
    current_price: float,
) -> tuple[float | None, float | None]:
    side_text = str(side).upper()
    if side_text == "BUY":
        risk = float(entry) - float(planned_stop)
        excursion = float(current_price) - float(entry)
    elif side_text == "SELL":
        risk = float(planned_stop) - float(entry)
        excursion = float(entry) - float(current_price)
    else:
        return None, None
    if not isfinite(risk) or risk <= 1e-12 or not isfinite(excursion):
        return None, None
    return risk, excursion / risk


def propose_protective_stop(
    *,
    side: str,
    stage: PositionStage,
    entry: float,
    current_price: float,
    current_stop: float,
    initial_risk: float,
    last_swing_low: float | None,
    last_swing_high: float | None,
) -> float | None:
    """Return a tighter canonical stop, or None when no safe improvement exists.

    The function never widens risk and never crowds the live market. At the TP1
    milestone it protects around entry with a small positive-R cushion. Once the
    runner reaches >=2R it may trail behind the latest M15 swing, while retaining
    at least 0.30R of live breathing room to avoid treating normal XAU noise as
    invalidation.
    """

    side_text = str(side).upper()
    if side_text not in {"BUY", "SELL"} or stage not in {
        PositionStage.PROTECT_RUNNER,
        PositionStage.TRAIL_RUNNER,
    }:
        return None
    values = (entry, current_price, current_stop, initial_risk)
    if not all(isfinite(float(value)) for value in values) or float(initial_risk) <= 0.0:
        return None

    r = float(initial_risk)
    entry_value = float(entry)
    market = float(current_price)
    stop = float(current_stop)
    min_live_distance = MIN_LIVE_STOP_DISTANCE_R * r

    if side_text == "BUY":
        base = entry_value + STOP_BE_BUFFER_R * r
        target = base
        if stage == PositionStage.TRAIL_RUNNER and last_swing_low is not None:
            structural = float(last_swing_low) - TRAIL_SWING_BUFFER_R * r
            target = max(target, structural)
        target = min(target, market - min_live_distance)
        if target <= stop + max(1e-9, 0.01 * r) or target >= market:
            return None
        return target

    base = entry_value - STOP_BE_BUFFER_R * r
    target = base
    if stage == PositionStage.TRAIL_RUNNER and last_swing_high is not None:
        structural = float(last_swing_high) + TRAIL_SWING_BUFFER_R * r
        target = min(target, structural)
    target = max(target, market + min_live_distance)
    if target >= stop - max(1e-9, 0.01 * r) or target <= market:
        return None
    return target


def _load_uncertain_ids(store: SupabaseOperationalStore) -> set[str]:
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
        return set()
    if not rows or not isinstance(rows[0].get("details"), dict):
        return set()
    return {str(value) for value in (rows[0]["details"].get("uncertain_position_ids") or [])}


def _exact_broker_identity(session, *, position_id: int, side: str) -> tuple[int, int, int] | None:
    reconcile = session.reconcile()
    matches = [
        position
        for position in tuple(getattr(reconcile, "position", ()))
        if int(getattr(position, "positionId", 0) or 0) == int(position_id)
    ]
    if len(matches) != 1:
        return None
    trade_data = getattr(matches[0], "tradeData", None)
    if trade_data is None:
        return None
    symbol_id = int(getattr(trade_data, "symbolId", 0) or 0)
    trade_side = int(getattr(trade_data, "tradeSide", 0) or 0)
    raw_volume = int(getattr(trade_data, "volume", 0) or 0)
    expected_side = 1 if str(side).upper() == "BUY" else 2 if str(side).upper() == "SELL" else 0
    if (
        symbol_id <= 0
        or symbol_id != int(session.symbol_id(SYMBOL))
        or trade_side != expected_side
        or raw_volume <= 0
    ):
        return None
    return symbol_id, trade_side, raw_volume


def _verify_stop(session, *, position_id: int, requested_stop: float, side: str) -> bool:
    for attempt in range(VERIFY_ATTEMPTS):
        reconcile = session.reconcile()
        matches = [
            position
            for position in tuple(getattr(reconcile, "position", ()))
            if int(getattr(position, "positionId", 0) or 0) == int(position_id)
        ]
        if len(matches) != 1:
            return False
        actual = _positive(getattr(matches[0], "stopLoss", None))
        if actual is not None:
            tolerance = max(1e-5, abs(float(requested_stop)) * 1e-8)
            if abs(actual - float(requested_stop)) <= tolerance:
                return True
            if str(side).upper() == "BUY" and actual > float(requested_stop):
                return True
            if str(side).upper() == "SELL" and actual < float(requested_stop):
                return True
        if attempt + 1 < VERIFY_ATTEMPTS:
            sleep(VERIFY_POLL_SECONDS)
    return False


def run() -> int:
    if os.getenv(FEATURE_ENV, "0").strip() != "1":
        print("CTRADER_DEMO_XAU_CANONICAL_POSITION_MANAGER_DISABLED")
        return 0

    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_CANONICAL_POSITION_MANAGER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_CANONICAL_POSITION_MANAGER_REQUIRE_DEMO")
    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("XAU_CANONICAL_POSITION_MANAGER_KILL_SWITCH_BLOCK")

    all_symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    uncertain = _load_uncertain_ids(store)
    protector = CTraderPostFillProtectionManager(
        session,
        quote_provider=gateway.market_quote,
        reconcile_attempts=3,
        amend_attempts=1,
        poll_seconds=0.20,
        amend_timeout_seconds=float(policy.ctrader.get("request_timeout_seconds", 10)),
    )

    evaluated = managed = stops_advanced = exits = skipped = failures = 0
    decisions: list[dict[str, Any]] = []
    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("XAU_CANONICAL_POSITION_MANAGER_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(session=session, store=store, phase="XAU_CANONICAL_MANAGER")
        raw_volumes = _raw_volume_by_position(session)

        for position in snapshot.positions:
            if str(position.symbol).upper() != SYMBOL:
                continue
            position_id = str(position.position_id)
            if position_id in uncertain:
                skipped += 1
                decisions.append({"position_id": position_id, "reason": "UNCERTAIN_OUTCOME_QUARANTINE"})
                continue

            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None:
                skipped += 1
                decisions.append({"position_id": position_id, "reason": "NOT_SCANNER_LINKED"})
                continue
            plan = _load_canonical_signal_plan(store, signal_id=signal_id)
            if plan is None:
                skipped += 1
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "NOT_CANONICAL_XAU_SIGNAL"})
                continue

            side = str(position.side).upper()
            expected_direction = "LONG" if side == "BUY" else "SHORT" if side == "SELL" else ""
            if str(plan.get("direction") or "").upper() != expected_direction:
                failures += 1
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "SIGNAL_POSITION_DIRECTION_MISMATCH"})
                continue

            current_price = _positive(position.current_price)
            current_stop = _positive(position.stop_loss)
            current_tp = _positive(position.take_profit)
            entry = _positive(position.open_price)
            planned_stop = _positive(plan.get("sl"))
            if None in {current_price, current_stop, current_tp, entry, planned_stop}:
                skipped += 1
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "PROTECTION_OR_PRICE_INCOMPLETE"})
                continue

            evaluated += 1
            initial_risk, current_r = _initial_risk_and_r(
                side=side,
                entry=float(entry),
                planned_stop=float(planned_stop),
                current_price=float(current_price),
            )
            if initial_risk is None or current_r is None:
                failures += 1
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": "INITIAL_R_GEOMETRY_INVALID"})
                continue

            try:
                m5 = _fetch_structure(session, symbol=SYMBOL, timeframe="M5", as_of=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc))
                m15 = _fetch_structure(session, symbol=SYMBOL, timeframe="M15", as_of=__import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc))
            except Exception as exc:
                skipped += 1
                decisions.append({"position_id": position_id, "signal_id": signal_id, "reason": f"STRUCTURE_UNAVAILABLE:{type(exc).__name__}"})
                continue

            structural_exit = evaluate_profit_protect(
                side=side,
                net_floating_pnl=position.profit,
                m5=m5,
                m15=m15,
            )
            management = evaluate_position_management(
                current_r=current_r,
                profitable=bool(position.profit is not None and float(position.profit) > 0.0),
                adverse_structure_confirmed=bool(structural_exit.close),
            )
            payload = {
                "strategy_id": STRATEGY_ID,
                "signal_id": signal_id,
                "position_id": position_id,
                "symbol": SYMBOL,
                "side": side,
                "open_price": entry,
                "current_price": current_price,
                "current_stop": current_stop,
                "take_profit": current_tp,
                "planned_initial_stop": planned_stop,
                "initial_risk_price": initial_risk,
                "current_r": current_r,
                "floating_pnl": position.profit,
                "management": asdict(management),
                "adverse_structure": asdict(structural_exit),
                "m15_last_swing_low": m15.last_swing_low,
                "m15_last_swing_high": m15.last_swing_high,
                "environment": "DEMO",
                "live_execution_enabled": False,
            }
            decisions.append(payload)
            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_XAU_CANONICAL_MANAGER_EVALUATION",
                    broker_order_id=f"XAU_CANONICAL_EVAL:{position_id}:{uuid4().hex[:8]}",
                    accepted=True,
                    code=management.stage.value,
                    message=management.reason,
                    payload=payload,
                )
            except Exception:
                failures += 1
                continue

            if management.exit_position:
                raw_volume = int(raw_volumes.get(int(position_id), 0) or 0)
                if raw_volume <= 0:
                    failures += 1
                    payload["execution"] = "RAW_VOLUME_UNAVAILABLE"
                    continue
                try:
                    store.record_order_event(
                        backend="CTRADER",
                        account_id=str(session.account_id),
                        signal_key=signal_id,
                        event_type="DEMO_XAU_CANONICAL_EXIT_REQUEST",
                        broker_order_id=f"XAU_CANONICAL_EXIT_REQUEST:{position_id}:{uuid4().hex[:8]}",
                        accepted=None,
                        code="ADVERSE_STRUCTURE_CONFIRMED",
                        message="canonical XAU protective exit requested",
                        payload=payload,
                    )
                except Exception:
                    failures += 1
                    continue
                status, detail = _close_full_position(
                    session,
                    position_id=int(position_id),
                    raw_volume=raw_volume,
                )
                payload["execution"] = status
                payload["execution_detail"] = detail
                if status == "CLOSED":
                    exits += 1
                    managed += 1
                    uncertain.discard(position_id)
                    store.record_order_event(
                        backend="CTRADER",
                        account_id=str(session.account_id),
                        signal_key=signal_id,
                        event_type="DEMO_XAU_CANONICAL_EXIT",
                        broker_order_id=f"XAU_CANONICAL_EXIT:{position_id}",
                        accepted=True,
                        code="CANONICAL_ADVERSE_STRUCTURE_EXIT",
                        message="canonical XAU position closed on confirmed adverse structure while profitable",
                        payload=payload,
                    )
                elif status == "UNCERTAIN":
                    uncertain.add(position_id)
                    failures += 1
                    store.record_order_event(
                        backend="CTRADER",
                        account_id=str(session.account_id),
                        signal_key=signal_id,
                        event_type="DEMO_XAU_CANONICAL_EXIT_UNCERTAIN",
                        broker_order_id=f"XAU_CANONICAL_EXIT_UNCERTAIN:{position_id}",
                        accepted=None,
                        code="OUTCOME_UNCERTAIN",
                        message=detail[:500],
                        payload=payload,
                    )
                else:
                    failures += 1
                continue

            if not management.protect_stop:
                continue

            target_stop = propose_protective_stop(
                side=side,
                stage=management.stage,
                entry=float(entry),
                current_price=float(current_price),
                current_stop=float(current_stop),
                initial_risk=float(initial_risk),
                last_swing_low=m15.last_swing_low,
                last_swing_high=m15.last_swing_high,
            )
            if target_stop is None:
                continue

            identity = _exact_broker_identity(session, position_id=int(position_id), side=side)
            if identity is None:
                failures += 1
                continue
            symbol_id, trade_side, raw_volume = identity
            try:
                validated_stop, validated_tp = protector._validate_planned_protection(
                    symbol_name=SYMBOL,
                    symbol_info=session.symbol_info(SYMBOL),
                    trade_side=trade_side,
                    stop_loss=float(target_stop),
                    take_profit=float(current_tp),
                )
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_XAU_CANONICAL_STOP_ADVANCE_REQUEST",
                    broker_order_id=f"XAU_CANONICAL_STOP_REQUEST:{position_id}:{uuid4().hex[:8]}",
                    accepted=None,
                    code=management.stage.value,
                    message="canonical XAU stop advance requested; risk cannot widen",
                    payload={**payload, "requested_stop": validated_stop},
                )
                protector._send_amend(
                    account_id=int(session.account_id),
                    position_id=int(position_id),
                    stop_loss=float(validated_stop),
                    take_profit=float(validated_tp),
                )
            except Exception as exc:
                failures += 1
                payload["stop_advance_error"] = f"{type(exc).__name__}:{exc}"
                continue

            if not _verify_stop(
                session,
                position_id=int(position_id),
                requested_stop=float(validated_stop),
                side=side,
            ):
                failures += 1
                continue
            stops_advanced += 1
            managed += 1
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                event_type="DEMO_XAU_CANONICAL_STOP_ADVANCED",
                broker_order_id=f"XAU_CANONICAL_STOP:{position_id}:{uuid4().hex[:8]}",
                accepted=True,
                code=management.stage.value,
                message="canonical XAU protective stop advanced and broker-verified",
                payload={**payload, "requested_stop": validated_stop},
            )

        healthy = failures == 0
        store.write_heartbeat(
            STATE_WORKER,
            healthy=healthy,
            lag_seconds=0.0,
            details={
                "strategy_id": STRATEGY_ID,
                "mode": "CANONICAL_XAU_POSITION_AWARE_DEMO_ONLY",
                "evaluated": evaluated,
                "managed": managed,
                "stops_advanced": stops_advanced,
                "protective_exits": exits,
                "skipped": skipped,
                "failures": failures,
                "uncertain_position_ids": sorted(uncertain),
                "decisions": decisions[-24:],
                "countertrend_auto_execution": False,
                "stop_widening_allowed": False,
                "live_unlock": False,
            },
        )
        print(
            "CTRADER_DEMO_XAU_CANONICAL_POSITION_MANAGER "
            f"evaluated={evaluated} managed={managed} stops_advanced={stops_advanced} "
            f"exits={exits} skipped={skipped} failures={failures} uncertain={len(uncertain)}"
        )
        return 0 if healthy else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

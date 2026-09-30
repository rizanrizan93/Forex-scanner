from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any
from uuid import UUID, uuid4

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .execution.ctrader_protection import CTraderPostFillProtectionManager
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

STATE_WORKER = "ctrader_demo_existing_protection_repair"
V229_CHILD_ID_RE = re.compile(r"^RZ229:[0-9a-f]{18}:L[1-4]$")


def _positive(value: Any) -> float | None:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _position_unprotected(position) -> bool:
    return _positive(position.stop_loss) is None or _positive(position.take_profit) is None


def _protection_gate_healthy(
    *,
    failed: int,
    unprotected_scanner_positions: list[str],
    unprotected_unmanaged_positions: list[str],
) -> bool:
    return (
        int(failed) == 0
        and not unprotected_scanner_positions
        and not unprotected_unmanaged_positions
    )


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


def _scanner_key_from_comment(comment: str | None, prefix: str) -> str | None:
    """Resolve only exact scanner-owned identities from broker comments."""
    signal_id = _signal_id_from_comment(comment, prefix)
    if signal_id is not None:
        return signal_id
    text = str(comment or "").strip()
    marker = f"{str(prefix).strip()}:"
    if not text.startswith(marker):
        return None
    candidate = text[len(marker):].strip()
    return candidate if V229_CHILD_ID_RE.fullmatch(candidate) else None


def _load_signal_plan(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    symbol: str,
    side: str,
) -> dict[str, Any] | None:
    response = (
        store.client.table("signals")
        .select("id,symbol,direction,sl,tp2")
        .eq("id", signal_id)
        .limit(2)
        .execute()
    )
    rows = [dict(row) for row in (response.data or [])]
    if len(rows) != 1:
        return None
    row = rows[0]
    expected_direction = "LONG" if str(side).upper() == "BUY" else "SHORT"
    if str(row.get("symbol", "")).upper() != str(symbol).upper():
        return None
    if str(row.get("direction", "")).upper() != expected_direction:
        return None
    if _positive(row.get("sl")) is None:
        return None
    return row


def _load_v229_child_plan(
    store: SupabaseOperationalStore,
    *,
    child_id: str,
    symbol: str,
    side: str,
) -> dict[str, Any] | None:
    """Recover immutable submitted SL/TP for an exact V229 child order."""
    if not V229_CHILD_ID_RE.fullmatch(str(child_id or "")):
        return None
    try:
        response = (
            store.client.table("broker_order_events")
            .select("signal_key,observed_at,event_type,accepted,broker_order_id,payload")
            .eq("signal_key", child_id)
            .eq("event_type", "ORDER_ACCEPTED")
            .eq("accepted", True)
            .order("observed_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return None

    rows = [dict(row) for row in (response.data or [])]
    if len(rows) != 1:
        return None
    row = rows[0]
    payload = dict(row.get("payload") or {})
    if str(payload.get("symbol") or "").upper() != str(symbol).upper():
        return None
    if str(payload.get("signal_id") or "") != str(child_id):
        return None

    entry = _positive(payload.get("requested_entry"))
    stop = _positive(payload.get("requested_stop_loss"))
    target = _positive(payload.get("requested_take_profit"))
    volume = _positive(payload.get("requested_volume"))
    if None in {entry, stop, target, volume}:
        return None

    side_text = str(side).upper()
    if side_text == "BUY":
        geometry_ok = float(stop) < float(entry) < float(target)
        direction = "LONG"
    elif side_text == "SELL":
        geometry_ok = float(target) < float(entry) < float(stop)
        direction = "SHORT"
    else:
        return None
    if not geometry_ok:
        return None

    return {
        "id": str(child_id),
        "symbol": str(symbol).upper(),
        "direction": direction,
        "sl": float(stop),
        "tp2": float(target),
        "entry": float(entry),
        "volume": float(volume),
        "broker_order_id": row.get("broker_order_id"),
        "source": "V229_CHILD_ORDER_ACCEPTED",
    }


def _load_repair_plan(
    store: SupabaseOperationalStore,
    *,
    scanner_key: str,
    symbol: str,
    side: str,
) -> dict[str, Any] | None:
    if V229_CHILD_ID_RE.fullmatch(str(scanner_key or "")):
        return _load_v229_child_plan(
            store,
            child_id=str(scanner_key),
            symbol=symbol,
            side=side,
        )
    return _load_signal_plan(
        store,
        signal_id=str(scanner_key),
        symbol=symbol,
        side=side,
    )


def _exact_broker_identity(session, *, position_id: int, symbol: str, side: str) -> tuple[int, int, int] | None:
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
    volume = int(getattr(trade_data, "volume", 0) or 0)
    expected_side = 1 if str(side).upper() == "BUY" else 2 if str(side).upper() == "SELL" else 0
    if symbol_id <= 0 or trade_side != expected_side or volume <= 0:
        return None
    if symbol_id != int(session.symbol_id(symbol)):
        return None
    return symbol_id, trade_side, volume


def _event_payload(
    *,
    position,
    signal_id: str,
    requested_sl: float,
    requested_tp: float,
    outcome=None,
) -> dict[str, Any]:
    payload = {
        "signal_id": signal_id,
        "position_id": str(position.position_id),
        "symbol": str(position.symbol).upper(),
        "side": str(position.side).upper(),
        "volume": float(position.volume),
        "open_price": float(position.open_price),
        "existing_sl": position.stop_loss,
        "existing_tp": position.take_profit,
        "requested_sl": float(requested_sl),
        "requested_tp": float(requested_tp),
        "repair_scope": "EXACT_SCANNER_LINKED_POSITION",
        "live_unlock": False,
    }
    if outcome is not None:
        payload["outcome"] = asdict(outcome)
    return payload


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_EXISTING_PROTECTION_REPAIR_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_EXISTING_PROTECTION_REPAIR_REQUIRE_DEMO")

    symbols = [pair.symbol for pair in cfg.pairs]
    gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    manager = CTraderPostFillProtectionManager(
        session,
        quote_provider=gateway.market_quote,
        reconcile_attempts=4,
        amend_attempts=2,
        poll_seconds=0.20,
        amend_timeout_seconds=float(policy.ctrader.get("request_timeout_seconds", 10)),
    )

    scanned = linked = repair_needed = repaired = failed = skipped = 0
    failures: list[dict[str, str]] = []
    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("CTRADER_EXISTING_PROTECTION_REPAIR_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(
            session=session,
            store=store,
            phase="PROTECTION_REPAIR_BEFORE",
        )
        for position in snapshot.positions:
            scanned += 1
            symbol = str(position.symbol).upper()
            side = str(position.side).upper()
            position_id = int(str(position.position_id))
            current_sl = _positive(position.stop_loss)
            current_tp = _positive(position.take_profit)
            if not _position_unprotected(position):
                continue

            scanner_key = _scanner_key_from_comment(position.comment, prefix)
            if scanner_key is None:
                skipped += 1
                continue
            signal = _load_repair_plan(
                store,
                scanner_key=scanner_key,
                symbol=symbol,
                side=side,
            )
            if signal is None:
                skipped += 1
                continue
            signal_id = scanner_key
            linked += 1

            identity = _exact_broker_identity(
                session,
                position_id=position_id,
                symbol=symbol,
                side=side,
            )
            if identity is None:
                failed += 1
                failures.append({"position_id": str(position_id), "code": "BROKER_IDENTITY_UNVERIFIED"})
                continue
            symbol_id, trade_side, raw_volume = identity

            requested_sl = current_sl or _positive(signal.get("sl"))
            requested_tp = current_tp or _positive(signal.get("tp2"))
            if requested_sl is None or requested_tp is None:
                failed += 1
                failures.append({"position_id": str(position_id), "code": "SIGNAL_PROTECTION_INCOMPLETE"})
                continue

            repair_needed += 1
            request_payload = _event_payload(
                position=position,
                signal_id=signal_id,
                requested_sl=requested_sl,
                requested_tp=requested_tp,
            )
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=signal_id,
                event_type="DEMO_EXISTING_PROTECTION_REPAIR_REQUEST",
                broker_order_id=f"EXISTING_PROTECT_REQUEST:{position_id}:{uuid4().hex[:8]}",
                accepted=None,
                code="MISSING_SL_OR_TP",
                message="targeted DEMO protection repair requested for exact scanner-linked position",
                payload=request_payload,
            )

            outcome = manager.ensure(
                account_id=int(session.account_id),
                position_id=position_id,
                symbol_name=symbol,
                symbol_info=session.symbol_info(symbol),
                expected_symbol_id=symbol_id,
                expected_trade_side=trade_side,
                expected_volume_cents=raw_volume,
                planned_stop_loss=requested_sl,
                planned_take_profit=requested_tp,
            )
            result_payload = _event_payload(
                position=position,
                signal_id=signal_id,
                requested_sl=requested_sl,
                requested_tp=requested_tp,
                outcome=outcome,
            )
            if outcome.verified:
                repaired += 1
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_EXISTING_PROTECTION_REPAIR_VERIFIED",
                    broker_order_id=f"EXISTING_PROTECT:{position_id}",
                    accepted=True,
                    code=outcome.code,
                    message=outcome.message,
                    payload=result_payload,
                )
            else:
                failed += 1
                failures.append({"position_id": str(position_id), "code": outcome.code})
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_EXISTING_PROTECTION_REPAIR_FAILED",
                    broker_order_id=f"EXISTING_PROTECT_FAILED:{position_id}:{uuid4().hex[:8]}",
                    accepted=False,
                    code=outcome.code,
                    message=outcome.message[:500],
                    payload=result_payload,
                )

        after = capture_ctrader_demo_snapshot(
            session=session,
            store=store,
            phase="PROTECTION_REPAIR_AFTER",
        )
        unprotected_scanner_positions: list[str] = []
        unprotected_unmanaged_positions: list[str] = []
        for position in after.positions:
            if not _position_unprotected(position):
                continue
            scanner_key = _scanner_key_from_comment(position.comment, prefix)
            if scanner_key is None:
                unprotected_unmanaged_positions.append(str(position.position_id))
            else:
                unprotected_scanner_positions.append(str(position.position_id))

        healthy = _protection_gate_healthy(
            failed=failed,
            unprotected_scanner_positions=unprotected_scanner_positions,
            unprotected_unmanaged_positions=unprotected_unmanaged_positions,
        )
        store.write_heartbeat(
            STATE_WORKER,
            healthy=healthy,
            lag_seconds=0.0,
            details={
                "mode": "DEMO_EXACT_POSITION_PROTECTION_REPAIR",
                "scanned": scanned,
                "scanner_linked_unprotected": linked,
                "repair_needed": repair_needed,
                "repaired": repaired,
                "failed": failed,
                "skipped_non_scanner_or_unusable": skipped,
                "unprotected_scanner_position_ids": unprotected_scanner_positions[-32:],
                "unprotected_unmanaged_position_ids": unprotected_unmanaged_positions[-32:],
                "new_orders_blocked_by_unprotected_unmanaged": bool(unprotected_unmanaged_positions),
                "failures": failures[-32:],
                "same_symbol_policy_mutated": False,
                "live_unlock": False,
            },
        )
        print(
            "CTRADER_DEMO_EXISTING_PROTECTION_REPAIR "
            f"scanned={scanned} linked={linked} needed={repair_needed} repaired={repaired} "
            f"failed={failed} remaining_scanner_unprotected={len(unprotected_scanner_positions)} "
            f"remaining_unmanaged_unprotected={len(unprotected_unmanaged_positions)}"
        )
        return 0 if healthy else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from ..demo_broker_pnl import capture_ctrader_demo_snapshot


@dataclass(frozen=True, slots=True)
class SymbolExposure:
    same_direction: int
    opposite_direction: int
    unmanaged: int


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


def _signal_matches_position(store, *, signal_id: str, symbol: str, side: str) -> bool:
    try:
        response = (
            store.client.table("signals")
            .select("id,symbol,direction")
            .eq("id", signal_id)
            .limit(2)
            .execute()
        )
        rows = list(response.data or [])
    except Exception:
        return False
    if len(rows) != 1:
        return False
    expected_direction = "LONG" if str(side).upper() == "BUY" else "SHORT"
    return bool(
        str(rows[0].get("symbol", "")).upper() == str(symbol).upper()
        and str(rows[0].get("direction", "")).upper() == expected_direction
    )


def _raw_volume_by_position(session) -> dict[int, int]:
    reconcile = session.reconcile()
    output: dict[int, int] = {}
    for position in tuple(getattr(reconcile, "position", ())):
        position_id = int(getattr(position, "positionId", 0) or 0)
        trade_data = getattr(position, "tradeData", None)
        raw_volume = int(getattr(trade_data, "volume", 0) or 0) if trade_data is not None else 0
        if position_id > 0 and raw_volume > 0:
            output[position_id] = raw_volume
    return output


def _position_still_open(session, position_id: int) -> bool:
    reconcile = session.reconcile()
    return any(
        int(getattr(position, "positionId", 0) or 0) == int(position_id)
        for position in tuple(getattr(reconcile, "position", ()))
    )


def close_full_position_once(session, *, position_id: int, raw_volume: int) -> tuple[str, str]:
    """Submit one full close request. Never blind-retry an uncertain close."""
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAClosePositionReq

    req = ProtoOAClosePositionReq()
    req.ctidTraderAccountId = int(session.account_id)
    req.positionId = int(position_id)
    req.volume = int(raw_volume)
    try:
        response = session._send_sync(
            req,
            client_msg_id=f"signal-reversal-{position_id}-{uuid4().hex[:8]}",
        )
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        if "cTrader API error" in str(exc):
            return "REJECTED", text
        return "UNCERTAIN", text

    execution_type = int(getattr(response, "executionType", -1) or -1)
    for _ in range(6):
        if not _position_still_open(session, position_id):
            return "CLOSED", str(execution_type)
        import time
        time.sleep(0.25)
    return "UNCERTAIN", f"execution_type={execution_type}:position_still_open_after_ack"


def inspect_symbol_exposure(*, session, store, symbol: str, direction: str, comment_prefix: str) -> SymbolExposure:
    wanted_side = "BUY" if str(direction).upper() == "LONG" else "SELL"
    snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="SIGNAL_TRANSITION")
    same = opposite = unmanaged = 0
    for position in snapshot.positions:
        if str(position.symbol).upper() != str(symbol).upper():
            continue
        signal_id = _signal_id_from_comment(position.comment, comment_prefix)
        managed = bool(
            signal_id
            and _signal_matches_position(
                store,
                signal_id=signal_id,
                symbol=symbol,
                side=position.side,
            )
        )
        if not managed:
            unmanaged += 1
        elif str(position.side).upper() == wanted_side:
            same += 1
        else:
            opposite += 1
    return SymbolExposure(same, opposite, unmanaged)


def close_opposite_symbol_positions(*, session, store, symbol: str, direction: str, new_signal_id: str, comment_prefix: str) -> str | None:
    """Close scanner-linked opposite positions before a qualified reversal entry."""
    wanted_side = "BUY" if str(direction).upper() == "LONG" else "SELL"
    snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="SIGNAL_REVERSAL")
    raw_volumes = _raw_volume_by_position(session)
    targets = []
    for position in snapshot.positions:
        if str(position.symbol).upper() != str(symbol).upper() or str(position.side).upper() == wanted_side:
            continue
        prior_signal_id = _signal_id_from_comment(position.comment, comment_prefix)
        if prior_signal_id is None or not _signal_matches_position(
            store,
            signal_id=prior_signal_id,
            symbol=symbol,
            side=position.side,
        ):
            return "BROKER_OPPOSITE_DIRECTION_UNMANAGED"
        targets.append((position, prior_signal_id))

    for position, prior_signal_id in targets:
        position_id = int(position.position_id)
        raw_volume = int(raw_volumes.get(position_id, 0) or 0)
        if raw_volume <= 0:
            return "BROKER_OPPOSITE_DIRECTION_RAW_VOLUME_UNAVAILABLE"
        payload: dict[str, Any] = {
            "symbol": str(symbol).upper(),
            "position_id": str(position_id),
            "prior_signal_id": prior_signal_id,
            "new_signal_id": str(new_signal_id),
            "prior_side": str(position.side).upper(),
            "new_direction": str(direction).upper(),
            "transition": "CLOSE_OPPOSITE_THEN_REEVALUATE_NEW_ENTRY",
        }
        try:
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=str(new_signal_id),
                event_type="DEMO_SIGNAL_REVERSAL_CLOSE_REQUEST",
                broker_order_id=f"REVERSAL_CLOSE_REQUEST:{position_id}:{uuid4().hex[:8]}",
                accepted=None,
                code="OPPOSITE_SIGNAL_QUALIFIED",
                message="close opposite scanner-linked position before new same-symbol entry",
                payload=payload,
            )
        except Exception:
            return "BROKER_OPPOSITE_DIRECTION_AUDIT_PERSIST_FAILED"

        status, detail = close_full_position_once(
            session,
            position_id=position_id,
            raw_volume=raw_volume,
        )
        try:
            store.record_order_event(
                backend="CTRADER",
                account_id=str(session.account_id),
                signal_key=str(new_signal_id),
                event_type="DEMO_SIGNAL_REVERSAL_CLOSE_RESULT",
                broker_order_id=f"REVERSAL_CLOSE_RESULT:{position_id}:{uuid4().hex[:8]}",
                accepted=status == "CLOSED",
                code=status,
                message=detail,
                payload=payload,
            )
        except Exception:
            return "BROKER_OPPOSITE_DIRECTION_AUDIT_PERSIST_FAILED"
        if status == "UNCERTAIN":
            return "BROKER_OPPOSITE_DIRECTION_CLOSE_UNCERTAIN"
        if status != "CLOSED":
            return f"BROKER_OPPOSITE_DIRECTION_CLOSE_{status}"

    remaining = inspect_symbol_exposure(
        session=session,
        store=store,
        symbol=symbol,
        direction=direction,
        comment_prefix=comment_prefix,
    )
    if remaining.unmanaged:
        return "BROKER_OPPOSITE_DIRECTION_UNMANAGED"
    if remaining.opposite_direction:
        return "BROKER_OPPOSITE_DIRECTION_STILL_OPEN"
    return None

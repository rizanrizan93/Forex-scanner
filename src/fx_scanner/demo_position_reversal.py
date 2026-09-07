from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import sleep
from typing import Any
from uuid import UUID, uuid4

from .execution.models import OrderSide

UTC = timezone.utc
STATE_WORKER = "ctrader_demo_reversal_position_policy"


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    position_id: int
    raw_volume: int
    side: str
    signal_id: str


@dataclass(frozen=True, slots=True)
class ExposurePlan:
    block: str | None
    same_direction: int
    managed_opposite: tuple[ManagedPosition, ...]
    unmanaged_opposite: tuple[int, ...]
    uncertain_opposite: tuple[int, ...]
    open_positions: int


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
    row = rows[0]
    expected = "LONG" if str(side).upper() == "BUY" else "SHORT"
    return bool(
        str(row.get("symbol", "")).upper() == str(symbol).upper()
        and str(row.get("direction", "")).upper() == expected
    )


def _load_uncertain(store) -> set[str]:
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
    return {str(x) for x in (rows[0]["details"].get("uncertain_position_ids") or [])}


def _write_state(store, uncertain: set[str], **extra: Any) -> None:
    details = {
        "policy": "SAME_DIRECTION_STACKING_GUARDED_OPPOSITE_REVERSAL",
        "uncertain_position_ids": sorted(uncertain),
        "manual_unmanaged_close_allowed": False,
        "uncertain_close_blind_retry": False,
        "post_close_revalidation_required": True,
        "live_unlock": False,
    }
    details.update(extra)
    try:
        store.write_heartbeat(STATE_WORKER, healthy=True, lag_seconds=0.0, details=details)
    except Exception:
        pass


def _classify_exposure(executor, intent, *, uncertain: set[str]) -> ExposurePlan:
    session = getattr(executor.gateway, "session", None)
    if session is None:
        try:
            count = int(executor.gateway.position_count())
        except Exception as exc:
            return ExposurePlan(
                f"BROKER_POSITION_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}",
                0,
                (),
                (),
                (),
                0,
            )
        maximum = int(executor.demo.get("max_concurrent_positions", 1))
        block = f"BROKER_CAPACITY_FULL:{count}/{maximum}" if count >= maximum else None
        return ExposurePlan(block, 0, (), (), (), count)

    try:
        session.ensure_connected()
        target_symbol_id = int(session.symbol_info(intent.symbol).symbolId)
        reconcile = session.reconcile()
        positions = tuple(getattr(reconcile, "position", ()))
    except Exception as exc:
        return ExposurePlan(
            f"BROKER_SYMBOL_RECONCILIATION_FAILED:{type(exc).__name__}:{exc}",
            0,
            (),
            (),
            (),
            0,
        )

    desired_side = "BUY" if intent.side == OrderSide.BUY else "SELL"
    prefix = str(executor.policy.order.get("comment_prefix", "FXIS"))
    same_direction = 0
    managed: list[ManagedPosition] = []
    unmanaged: list[int] = []
    quarantined: list[int] = []

    open_ids = {
        str(int(getattr(position, "positionId", 0) or 0))
        for position in positions
        if int(getattr(position, "positionId", 0) or 0) > 0
    }
    uncertain.intersection_update(open_ids)

    for position in positions:
        position_id = int(getattr(position, "positionId", 0) or 0)
        trade_data = getattr(position, "tradeData", None)
        if position_id <= 0 or trade_data is None:
            continue
        position_symbol_id = int(getattr(trade_data, "symbolId", 0) or 0)
        if position_symbol_id != target_symbol_id:
            continue
        side_code = int(getattr(trade_data, "tradeSide", 0) or 0)
        side = "BUY" if side_code == 1 else "SELL" if side_code == 2 else "UNKNOWN"
        if side == desired_side:
            same_direction += 1
            continue

        if str(position_id) in uncertain:
            quarantined.append(position_id)
            continue

        signal_id = _signal_id_from_comment(getattr(trade_data, "comment", None), prefix)
        raw_volume = int(getattr(trade_data, "volume", 0) or 0)
        if (
            side not in {"BUY", "SELL"}
            or signal_id is None
            or raw_volume <= 0
            or not _signal_matches_position(
                executor.store,
                signal_id=signal_id,
                symbol=intent.symbol,
                side=side,
            )
        ):
            unmanaged.append(position_id)
            continue
        managed.append(ManagedPosition(position_id, raw_volume, side, signal_id))

    maximum = int(executor.demo.get("max_concurrent_positions", 1))
    if unmanaged:
        block = "UNMANAGED_OPPOSITE_EXPOSURE:" + ",".join(str(x) for x in unmanaged)
    elif quarantined:
        block = "REVERSAL_CLOSE_UNCERTAIN_QUARANTINE:" + ",".join(
            str(x) for x in quarantined
        )
    elif not managed and len(positions) >= maximum:
        block = f"BROKER_CAPACITY_FULL:{len(positions)}/{maximum}"
    else:
        block = None

    return ExposurePlan(
        block,
        same_direction,
        tuple(managed),
        tuple(unmanaged),
        tuple(quarantined),
        len(positions),
    )


def _position_still_open(session, position_id: int) -> bool:
    reconcile = session.reconcile()
    return any(
        int(getattr(position, "positionId", 0) or 0) == int(position_id)
        for position in tuple(getattr(reconcile, "position", ()))
    )


def _close_full_position(session, *, position_id: int, raw_volume: int) -> tuple[str, str]:
    """One full close request. Transport ambiguity is quarantined, never retried."""
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAClosePositionReq

    req = ProtoOAClosePositionReq()
    req.ctidTraderAccountId = int(session.account_id)
    req.positionId = int(position_id)
    req.volume = int(raw_volume)
    try:
        response = session._send_sync(
            req,
            client_msg_id=f"reversal-close-{position_id}-{uuid4().hex[:8]}",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}:{exc}"
        if "cTrader API error" in str(exc):
            return "REJECTED", detail
        return "UNCERTAIN", detail

    execution_type = int(getattr(response, "executionType", -1) or -1)
    for _ in range(6):
        if not _position_still_open(session, position_id):
            return "CLOSED", str(execution_type)
        sleep(0.25)
    return "UNCERTAIN", f"execution_type={execution_type}:position_still_open_after_ack"


def _audit_close(executor, *, position: ManagedPosition, event_type: str, accepted, code: str, message: str) -> None:
    session = executor.gateway.session
    try:
        executor.store.record_order_event(
            backend="CTRADER",
            account_id=str(session.account_id),
            signal_key=position.signal_id,
            event_type=event_type,
            broker_order_id=f"REVERSAL:{position.position_id}:{uuid4().hex[:8]}",
            accepted=accepted,
            code=code,
            message=message[:500],
            payload={
                "position_id": position.position_id,
                "side": position.side,
                "raw_volume": position.raw_volume,
                "policy": "SCANNER_LINKED_OPPOSITE_ONLY",
            },
        )
    except Exception:
        pass


def _close_managed_opposites(executor, positions: tuple[ManagedPosition, ...], uncertain: set[str]) -> tuple[bool, str | None]:
    session = executor.gateway.session
    for position in positions:
        _audit_close(
            executor,
            position=position,
            event_type="DEMO_REVERSAL_CLOSE_REQUEST",
            accepted=None,
            code="OPPOSITE_SIGNAL_VALID",
            message="scanner-linked opposite position close requested",
        )
        status, detail = _close_full_position(
            session,
            position_id=position.position_id,
            raw_volume=position.raw_volume,
        )
        if status == "CLOSED":
            uncertain.discard(str(position.position_id))
            _audit_close(
                executor,
                position=position,
                event_type="DEMO_REVERSAL_CLOSE_CONFIRMED",
                accepted=True,
                code="CLOSED",
                message=detail,
            )
            continue
        if status == "UNCERTAIN":
            uncertain.add(str(position.position_id))
            _audit_close(
                executor,
                position=position,
                event_type="DEMO_REVERSAL_CLOSE_UNCERTAIN",
                accepted=None,
                code="OUTCOME_UNCERTAIN",
                message=detail,
            )
            return False, f"REVERSAL_CLOSE_UNCERTAIN:{position.position_id}"
        _audit_close(
            executor,
            position=position,
            event_type="DEMO_REVERSAL_CLOSE_REJECTED",
            accepted=False,
            code="BROKER_REJECTED",
            message=detail,
        )
        return False, f"REVERSAL_CLOSE_REJECTED:{position.position_id}"
    return True, None


def _poll_once_with_position_policy(self, *, limit: int = 10):
    from .execution.demo_autotrade import DemoAutoReport

    if self.policy.live_safety.get("require_control_plane", False):
        if self.control_gate is None:
            return DemoAutoReport(0, 0, 0, 0, ("CONTROL_PLANE_BLOCKED:NOT_CONFIGURED",))
        try:
            self.control_gate.assert_orders_allowed(self.policy.mode.value)
        except Exception as exc:
            return DemoAutoReport(
                0,
                0,
                0,
                0,
                (f"CONTROL_PLANE_BLOCKED:{type(exc).__name__}:{exc}",),
            )

    rows = self.store.list_execution_ready_signals(limit=limit)
    uncertain = _load_uncertain(self.store)
    eligible = claimed = executed = 0
    skipped: list[str] = []

    for row in rows:
        signal_id = str(row.get("id", "UNKNOWN"))
        try:
            intent, reason = self._intent_with_transport_retry(
                row,
                now=datetime.now(tz=UTC),
            )
        except Exception as exc:
            skipped.append(f"{signal_id}:INTENT_ERROR:{type(exc).__name__}:{exc}")
            continue
        if intent is None:
            skipped.append(f"{signal_id}:NOT_ELIGIBLE:{reason or 'UNKNOWN'}")
            continue
        eligible += 1

        plan = _classify_exposure(self, intent, uncertain=uncertain)
        if plan.block is not None:
            skipped.append(f"{signal_id}:{plan.block}")
            continue

        try:
            if not self.store.claim_signal_for_execution(intent.signal_id):
                skipped.append(f"{signal_id}:CLAIM_LOST")
                continue
            claimed += 1
        except Exception as exc:
            skipped.append(f"{signal_id}:CLAIM_ERROR:{type(exc).__name__}:{exc}")
            continue

        if plan.managed_opposite:
            closed, close_failure = _close_managed_opposites(
                self,
                plan.managed_opposite,
                uncertain,
            )
            _write_state(
                self.store,
                uncertain,
                last_signal_id=signal_id,
                last_action="OPPOSITE_CLOSE",
                last_result="CLOSED" if closed else close_failure,
            )
            if not closed:
                skipped.append(f"{signal_id}:{close_failure or 'REVERSAL_CLOSE_FAILED'}")
                continue

            # Mandatory post-close revalidation. Existing intent geometry is not
            # reused blindly after the broker-side close side effect.
            try:
                intent, reason = self._intent_with_transport_retry(
                    row,
                    now=datetime.now(tz=UTC),
                )
            except Exception as exc:
                skipped.append(
                    f"{signal_id}:POST_REVERSAL_INTENT_ERROR:{type(exc).__name__}:{exc}"
                )
                continue
            if intent is None:
                skipped.append(
                    f"{signal_id}:POST_REVERSAL_NOT_ELIGIBLE:{reason or 'UNKNOWN'}"
                )
                continue

            # Reconcile capacity and same-symbol exposure again after the close.
            # The durable signal's active_guards are rechecked by _intent, which
            # preserves correlation/data-quality blocks from the fresh producer.
            post_plan = _classify_exposure(self, intent, uncertain=uncertain)
            if post_plan.block is not None or post_plan.managed_opposite:
                detail = post_plan.block or "OPPOSITE_EXPOSURE_REAPPEARED"
                skipped.append(f"{signal_id}:POST_REVERSAL_EXPOSURE_BLOCK:{detail}")
                continue

        accepted, failure = self._execute_claimed_with_retry(intent)
        if accepted:
            executed += 1
        elif failure is not None:
            skipped.append(f"{signal_id}:{failure}")
        else:
            skipped.append(f"{signal_id}:BROKER_NOT_ACCEPTED")

    _write_state(
        self.store,
        uncertain,
        scanned=len(rows),
        eligible=eligible,
        claimed=claimed,
        executed=executed,
    )
    return DemoAutoReport(
        scanned=len(rows),
        eligible=eligible,
        claimed=claimed,
        executed=executed,
        skipped=tuple(skipped),
    )


def install_demo_position_policy() -> None:
    """Install DEMO-only same-direction stacking and guarded reversal semantics."""
    from .execution.demo_autotrade import CTraderDemoAutoExecutor

    CTraderDemoAutoExecutor.poll_once = _poll_once_with_position_policy

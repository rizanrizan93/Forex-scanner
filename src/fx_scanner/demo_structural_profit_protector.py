from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any
from uuid import UUID, uuid4

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .demo_broker_pnl import capture_ctrader_demo_snapshot
from .demo_market_schedule import apply_demo_market_schedule
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore
from .technical import StructureSnapshot, structure_snapshot

UTC = timezone.utc
STATE_WORKER = "ctrader_demo_structural_profit_protector"
FEATURE_ENV = "CTRADER_DEMO_STRUCTURAL_PROFIT_PROTECT_ENABLED"


@dataclass(frozen=True, slots=True)
class ProfitProtectDecision:
    close: bool
    reason: str
    opposite_direction: str | None
    m5_transition: bool
    m15_confirmation: bool


def _valid_displacement(snapshot: StructureSnapshot, wanted: str) -> bool:
    displacement = snapshot.displacement
    return bool(
        displacement is not None
        and displacement.valid
        and displacement.direction == wanted
    )


def _confirmed_transition(snapshot: StructureSnapshot, wanted: str) -> bool:
    """Require an adverse MSS, or BOS confirmed by adverse displacement."""
    return bool(
        snapshot.mss == wanted
        or (snapshot.bos == wanted and _valid_displacement(snapshot, wanted))
    )


def _higher_timeframe_confirmation(snapshot: StructureSnapshot, wanted: str) -> bool:
    """Conservative M15 confirmation for an M5 reversal trigger."""
    return bool(
        _confirmed_transition(snapshot, wanted)
        or (snapshot.trend == wanted and _valid_displacement(snapshot, wanted))
    )


def evaluate_profit_protect(
    *,
    side: str,
    net_floating_pnl: float | None,
    m5: StructureSnapshot,
    m15: StructureSnapshot,
) -> ProfitProtectDecision:
    side = str(side).upper()
    if side not in {"BUY", "SELL"}:
        return ProfitProtectDecision(False, "SIDE_INVALID", None, False, False)
    if net_floating_pnl is None or float(net_floating_pnl) <= 0.0:
        return ProfitProtectDecision(False, "NOT_IN_NET_PROFIT", None, False, False)

    opposite = "BEARISH" if side == "BUY" else "BULLISH"
    m5_transition = _confirmed_transition(m5, opposite)
    m15_confirmation = _higher_timeframe_confirmation(m15, opposite)
    if not m5_transition:
        return ProfitProtectDecision(
            False, "NO_CONFIRMED_M5_REVERSAL", opposite, False, m15_confirmation
        )
    if not m15_confirmation:
        return ProfitProtectDecision(
            False, "M15_REVERSAL_NOT_CONFIRMED", opposite, True, False
        )
    return ProfitProtectDecision(
        True, "CONFIRMED_ADVERSE_STRUCTURE_WHILE_PROFITABLE", opposite, True, True
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
        return {"uncertain_position_ids": []}
    if not rows or not isinstance(rows[0].get("details"), dict):
        return {"uncertain_position_ids": []}
    return dict(rows[0]["details"])


def _signal_matches_position(
    store: SupabaseOperationalStore,
    *,
    signal_id: str,
    symbol: str,
    side: str,
) -> bool:
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
    expected_direction = "LONG" if str(side).upper() == "BUY" else "SHORT"
    return bool(
        str(row.get("symbol", "")).upper() == str(symbol).upper()
        and str(row.get("direction", "")).upper() == expected_direction
    )


def _fetch_structure(session, *, symbol: str, timeframe: str, as_of: datetime) -> StructureSnapshot:
    timeframe_seconds = {"M5": 300, "M15": 900}[timeframe]
    count = 80
    fetched = tuple(
        session.historical_bars(
            symbol,
            timeframe,
            from_time=as_of - timedelta(seconds=timeframe_seconds * (count + 20)),
            to_time=as_of,
            count=count,
        )
    )
    closed = _closed_bars(
        fetched,
        as_of=as_of,
        timeframe_seconds=timeframe_seconds,
    )
    if len(closed) < 30:
        raise RuntimeError(f"{symbol}:{timeframe}:INSUFFICIENT_CLOSED_BARS")
    return structure_snapshot(list(closed[-60:]), swing_lookback=2, atr_period=14, sweep_reclaim_bars=3)


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


def _close_full_position(session, *, position_id: int, raw_volume: int) -> tuple[str, str]:
    """Send one full close request; never blind-retry an uncertain submission."""
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAClosePositionReq

    req = ProtoOAClosePositionReq()
    req.ctidTraderAccountId = int(session.account_id)
    req.positionId = int(position_id)
    req.volume = int(raw_volume)
    try:
        response = session._send_sync(
            req,
            client_msg_id=f"profit-protect-{position_id}-{uuid4().hex[:8]}",
        )
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        # A broker/API rejection is a known no-fill outcome. Transport timeout,
        # disconnect, or decode ambiguity is quarantined instead of retried.
        if "cTrader API error" in str(exc):
            return "REJECTED", text
        return "UNCERTAIN", text

    execution_type = int(getattr(response, "executionType", -1) or -1)
    for _ in range(6):
        if not _position_still_open(session, position_id):
            return "CLOSED", str(execution_type)
        sleep(0.25)
    return "UNCERTAIN", f"execution_type={execution_type}:position_still_open_after_ack"


def _snapshot_payload(snapshot: StructureSnapshot) -> dict[str, Any]:
    displacement = snapshot.displacement
    return {
        "trend": snapshot.trend,
        "bos": snapshot.bos,
        "mss": snapshot.mss,
        "last_swing_high": snapshot.last_swing_high,
        "last_swing_low": snapshot.last_swing_low,
        "displacement_direction": None if displacement is None else displacement.direction,
        "displacement_valid": False if displacement is None else bool(displacement.valid),
    }


def run() -> int:
    if os.getenv(FEATURE_ENV, "0").strip() != "1":
        print("CTRADER_DEMO_PROFIT_PROTECT_DISABLED")
        return 0

    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_PROFIT_PROTECT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_PROFIT_PROTECT_REQUIRE_DEMO")
    kill_name = str(policy.live_safety.get("kill_switch_env", "FX_KILL_SWITCH"))
    kill_safe = str(policy.live_safety.get("kill_switch_safe_value", "0"))
    if os.getenv(kill_name, "") != kill_safe:
        raise SystemExit("CTRADER_DEMO_PROFIT_PROTECT_KILL_SWITCH_BLOCK")

    active_symbols = {pair.symbol for pair in cfg.pairs}
    all_cfg = load_project_config(None)
    all_symbols = [pair.symbol for pair in all_cfg.pairs]
    gateway, session = build_broker_gateway(policy, all_symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    state = _load_state(store)
    uncertain = {str(x) for x in (state.get("uncertain_position_ids") or [])}
    prefix = str(policy.order.get("comment_prefix", "FXIS"))
    evaluated = eligible = closed = rejected = quarantined = 0
    decisions: list[dict[str, Any]] = []

    try:
        control = store.get_execution_control()
        if control.execution_mode != "AUTO" or control.emergency_stop:
            raise SystemExit("CTRADER_DEMO_PROFIT_PROTECT_CONTROL_PLANE_BLOCK")

        snapshot = capture_ctrader_demo_snapshot(session=session, store=None, phase="PROTECT")
        raw_volumes = _raw_volume_by_position(session)
        now = datetime.now(tz=UTC)

        for position in snapshot.positions:
            position_id = str(position.position_id)
            symbol = str(position.symbol).upper()
            if symbol not in active_symbols:
                decisions.append({"position_id": position_id, "symbol": symbol, "reason": "OUTSIDE_ACTIVE_MARKET_SCHEDULE"})
                continue
            if position_id in uncertain:
                quarantined += 1
                decisions.append({"position_id": position_id, "symbol": symbol, "reason": "UNCERTAIN_OUTCOME_QUARANTINE"})
                print(f"CTRADER_DEMO_PROFIT_PROTECT_SKIP symbol={symbol} position_id={position_id} reason=UNCERTAIN_OUTCOME_QUARANTINE")
                continue

            signal_id = _signal_id_from_comment(position.comment, prefix)
            if signal_id is None or not _signal_matches_position(
                store,
                signal_id=signal_id,
                symbol=symbol,
                side=position.side,
            ):
                decisions.append({"position_id": position_id, "symbol": symbol, "reason": "NOT_SCANNER_LINKED"})
                continue

            evaluated += 1
            try:
                m5 = _fetch_structure(session, symbol=symbol, timeframe="M5", as_of=now)
                m15 = _fetch_structure(session, symbol=symbol, timeframe="M15", as_of=now)
            except Exception as exc:
                reason = f"STRUCTURE_UNAVAILABLE:{type(exc).__name__}"
                decisions.append({"position_id": position_id, "symbol": symbol, "reason": reason})
                print(f"CTRADER_DEMO_PROFIT_PROTECT_SKIP symbol={symbol} position_id={position_id} reason={reason}")
                continue

            decision = evaluate_profit_protect(
                side=position.side,
                net_floating_pnl=position.profit,
                m5=m5,
                m15=m15,
            )
            decision_payload = {
                "position_id": position_id,
                "signal_id": signal_id,
                "symbol": symbol,
                "side": position.side,
                "floating_pnl": position.profit,
                "decision": decision.reason,
                "m5_transition": decision.m5_transition,
                "m15_confirmation": decision.m15_confirmation,
                "opposite_direction": decision.opposite_direction,
                "m5": _snapshot_payload(m5),
                "m15": _snapshot_payload(m15),
                "exit_model": "STRUCTURAL_PROFIT_PROTECT",
                "tp_mutated": False,
                "sl_mutated": False,
            }
            decisions.append(decision_payload)
            print(
                "CTRADER_DEMO_PROFIT_PROTECT_EVIDENCE "
                f"symbol={symbol} position_id={position_id} floating_pnl={float(position.profit or 0.0):.8g} "
                f"decision={decision.reason} m5_reversal={int(decision.m5_transition)} "
                f"m15_confirm={int(decision.m15_confirmation)}"
            )
            if not decision.close:
                continue

            raw_volume = int(raw_volumes.get(int(position_id), 0) or 0)
            if raw_volume <= 0:
                decisions[-1]["execution"] = "RAW_VOLUME_UNAVAILABLE"
                continue
            eligible += 1

            try:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_STRUCTURAL_PROFIT_PROTECT_REQUEST",
                    broker_order_id=f"PROFIT_PROTECT_REQUEST:{position_id}:{uuid4().hex[:8]}",
                    accepted=None,
                    code="REVERSAL_CONFIRMED",
                    message="full-position protective close requested before TP",
                    payload=decision_payload,
                )
            except Exception as exc:
                decisions[-1]["execution"] = f"AUDIT_PERSIST_FAILED:{type(exc).__name__}"
                continue

            status, detail = _close_full_position(
                session,
                position_id=int(position_id),
                raw_volume=raw_volume,
            )
            decisions[-1]["execution"] = status
            decisions[-1]["execution_detail"] = detail
            if status == "CLOSED":
                closed += 1
                uncertain.discard(position_id)
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_STRUCTURAL_PROFIT_PROTECT_EXIT",
                    broker_order_id=f"PROFIT_PROTECT:{position_id}",
                    accepted=True,
                    code="STRUCTURAL_PROTECT_PROFIT",
                    message="profitable position closed on confirmed adverse structure",
                    payload=decision_payload,
                )
                print(f"CTRADER_DEMO_PROFIT_PROTECT_CLOSED symbol={symbol} position_id={position_id} signal_id={signal_id}")
            elif status == "REJECTED":
                rejected += 1
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_STRUCTURAL_PROFIT_PROTECT_REJECTED",
                    broker_order_id=f"PROFIT_PROTECT_REJECTED:{position_id}:{uuid4().hex[:8]}",
                    accepted=False,
                    code="BROKER_REJECTED",
                    message=detail[:500],
                    payload=decision_payload,
                )
            else:
                quarantined += 1
                uncertain.add(position_id)
                store.record_order_event(
                    backend="CTRADER",
                    account_id=str(session.account_id),
                    signal_key=signal_id,
                    event_type="DEMO_STRUCTURAL_PROFIT_PROTECT_UNCERTAIN",
                    broker_order_id=f"PROFIT_PROTECT_UNCERTAIN:{position_id}",
                    accepted=None,
                    code="OUTCOME_UNCERTAIN",
                    message=detail[:500],
                    payload=decision_payload,
                )
                print(f"CTRADER_DEMO_PROFIT_PROTECT_QUARANTINE symbol={symbol} position_id={position_id}")

        store.write_heartbeat(
            STATE_WORKER,
            healthy=True,
            lag_seconds=0.0,
            details={
                "market_schedule": market_schedule_mode,
                "evaluated_scanner_positions": evaluated,
                "eligible_structural_exits": eligible,
                "confirmed_closed": closed,
                "broker_rejected": rejected,
                "quarantined": quarantined,
                "uncertain_position_ids": sorted(uncertain)[-64:],
                "last_decisions": decisions[-32:],
                "automatic_trade_management": True,
                "automatic_strategy_mutation": False,
                "exit_model": "PROFIT+M5_ADVERSE_TRANSITION+M15_CONFIRMATION",
                "fixed_trailing_stop": False,
                "fixed_break_even": False,
                "server_side_tp_preserved_until_market_close": True,
            },
        )
        print(
            "CTRADER_DEMO_PROFIT_PROTECT_OK "
            f"market_schedule={market_schedule_mode} evaluated={evaluated} eligible={eligible} "
            f"closed={closed} rejected={rejected} quarantined={quarantined}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .execution.broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerPositionSnapshot,
)

UTC = timezone.utc
TRAJECTORY_WORKER = "ctrader_demo_trajectory_state"
TRAJECTORY_MAX_POSITIONS = 128


@dataclass(frozen=True, slots=True)
class DemoBrokerSnapshot:
    account: BrokerAccountSnapshot
    positions: tuple[BrokerPositionSnapshot, ...]
    snapshot_id: str | None


def _money(value: Any, digits: Any) -> float:
    return float(value or 0) / (10 ** int(digits or 0))


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None


def _opened_at(trade_data: Any) -> datetime | None:
    raw = int(getattr(trade_data, "openTimestamp", 0) or 0)
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw / 1000.0, tz=UTC)


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _load_trajectory_state(store) -> dict[str, Any]:
    if store is None or not hasattr(store, "client"):
        return {"version": 1, "positions": {}}
    try:
        response = (
            store.client.table("runtime_heartbeats")
            .select("details")
            .eq("worker_name", TRAJECTORY_WORKER)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
    except Exception as exc:
        print(f"CTRADER_DEMO_TRAJECTORY_WARN stage=READ error={type(exc).__name__}")
        return {"version": 1, "positions": {}}
    if not rows or not isinstance(rows[0].get("details"), dict):
        return {"version": 1, "positions": {}}
    details = dict(rows[0]["details"])
    positions = details.get("positions")
    details["positions"] = dict(positions) if isinstance(positions, dict) else {}
    details["version"] = 1
    return details


def _update_sampled_trajectory(store, positions: tuple[BrokerPositionSnapshot, ...]) -> dict[str, dict[str, Any]]:
    """Maintain bounded sampled MAE/MFE in account-currency net floating P&L.

    These are explicitly sampled extrema at the pipeline cadence, not tick-level
    intrabar extrema. Keeping that distinction avoids false precision while
    still providing reliable evidence about whether trades first moved in our
    favor or against us before closing.
    """
    if store is None or not hasattr(store, "client"):
        return {}
    now = datetime.now(tz=UTC).isoformat()
    state = _load_trajectory_state(store)
    history = dict(state.get("positions") or {})
    current: dict[str, dict[str, Any]] = {}

    for position in positions:
        position_id = str(position.position_id)
        previous = history.get(position_id)
        previous = dict(previous) if isinstance(previous, dict) else {}
        pnl = _finite_float(position.profit)
        sample_count = int(previous.get("sample_count", 0) or 0)
        mae = _finite_float(previous.get("sampled_mae_pnl"))
        mfe = _finite_float(previous.get("sampled_mfe_pnl"))
        if mae is None:
            mae = 0.0
        if mfe is None:
            mfe = 0.0
        if pnl is not None:
            mae = min(0.0, mae, pnl)
            mfe = max(0.0, mfe, pnl)
            sample_count += 1
        item = {
            "position_id": position_id,
            "symbol": str(position.symbol).upper(),
            "side": str(position.side).upper(),
            "opened_at": None if position.opened_at is None else position.opened_at.isoformat(),
            "sampling_started_at": previous.get("sampling_started_at") or now,
            "last_sample_at": now,
            "sample_count": sample_count,
            "sampled_mae_pnl": mae,
            "sampled_mfe_pnl": mfe,
            "last_floating_pnl": pnl,
            "trajectory_scope": "SINCE_FIRST_OBSERVED",
            "metric": "NET_UNREALIZED_PNL_ACCOUNT_CURRENCY",
            "target_sample_cadence_seconds": 120,
        }
        history[position_id] = item
        current[position_id] = item

    if len(history) > TRAJECTORY_MAX_POSITIONS:
        ordered = sorted(
            history.items(),
            key=lambda pair: str((pair[1] or {}).get("last_sample_at", "")),
            reverse=True,
        )
        history = dict(ordered[:TRAJECTORY_MAX_POSITIONS])

    state.update(
        {
            "version": 1,
            "positions": history,
            "current_open_position_ids": sorted(current),
            "sampling_definition": "pipeline-sampled net unrealized P&L extrema",
            "automatic_exit_mutation": False,
        }
    )
    try:
        store.write_heartbeat(
            TRAJECTORY_WORKER,
            healthy=True,
            lag_seconds=0.0,
            details=state,
        )
    except Exception as exc:
        print(f"CTRADER_DEMO_TRAJECTORY_WARN stage=WRITE error={type(exc).__name__}")
        return {}

    for position_id, item in sorted(current.items(), key=lambda pair: (pair[1]["symbol"], pair[0])):
        print(
            "CTRADER_DEMO_POSITION_TRAJECTORY "
            f"symbol={item['symbol']} position_id={position_id} samples={item['sample_count']} "
            f"sampled_mae_pnl={float(item['sampled_mae_pnl']):.8g} "
            f"sampled_mfe_pnl={float(item['sampled_mfe_pnl']):.8g} "
            f"last_floating_pnl={'NONE' if item['last_floating_pnl'] is None else f'{float(item['last_floating_pnl']):.8g}'} "
            "scope=SINCE_FIRST_OBSERVED"
        )
    return current


def capture_ctrader_demo_snapshot(
    *,
    session,
    store=None,
    phase: str = "AFTER",
) -> DemoBrokerSnapshot:
    """Capture one coherent DEMO account/open-position P&L snapshot."""

    session.ensure_connected()
    trader = session.trader()
    pnl_res = session.unrealized_pnl()
    reconcile = session.reconcile()

    balance = _money(getattr(trader, "balance", 0), getattr(trader, "moneyDigits", 0))
    pnl_digits = int(getattr(pnl_res, "moneyDigits", 0) or 0)
    pnl_by_position: dict[int, float] = {}
    floating_profit = 0.0
    for item in tuple(getattr(pnl_res, "positionUnrealizedPnL", ())):
        position_id = int(getattr(item, "positionId", 0) or 0)
        net = _money(getattr(item, "netUnrealizedPnL", 0), pnl_digits)
        floating_profit += net
        if position_id > 0:
            pnl_by_position[position_id] = net

    used_margin = 0.0
    positions: list[BrokerPositionSnapshot] = []
    symbol_names = dict(getattr(session, "symbol_name_by_id", {}) or {})
    symbol_info = dict(getattr(session, "symbol_full_by_id", {}) or {})

    for position in tuple(getattr(reconcile, "position", ())):
        raw_margin = getattr(position, "usedMargin", 0)
        money_digits = int(getattr(position, "moneyDigits", 0) or 0)
        if raw_margin:
            used_margin += _money(raw_margin, money_digits)

        position_id = int(getattr(position, "positionId", 0) or 0)
        trade_data = getattr(position, "tradeData", None)
        if position_id <= 0 or trade_data is None:
            continue
        symbol_id = int(getattr(trade_data, "symbolId", 0) or 0)
        symbol = str(symbol_names.get(symbol_id, "")).upper().strip()
        if not symbol:
            continue

        side_code = int(getattr(trade_data, "tradeSide", 0) or 0)
        side = "BUY" if side_code == 1 else "SELL" if side_code == 2 else "UNKNOWN"
        info = symbol_info.get(symbol_id)
        lot_size = int(getattr(info, "lotSize", 0) or 0) if info is not None else 0
        raw_volume = int(getattr(trade_data, "volume", 0) or 0)
        volume = float(raw_volume) / float(lot_size) if lot_size > 0 else 0.0

        swap_raw = getattr(position, "swap", None)
        swap = None if swap_raw is None else _money(swap_raw, money_digits)
        comment = str(getattr(trade_data, "comment", "") or "").strip() or None
        positions.append(
            BrokerPositionSnapshot(
                backend=BrokerBackend.CTRADER,
                position_id=str(position_id),
                symbol=symbol,
                side=side,
                volume=volume,
                open_price=float(getattr(position, "price", 0.0) or 0.0),
                current_price=None,
                stop_loss=_positive_float(getattr(position, "stopLoss", None)),
                take_profit=_positive_float(getattr(position, "takeProfit", None)),
                profit=pnl_by_position.get(position_id),
                swap=swap,
                magic=None,
                comment=comment,
                opened_at=_opened_at(trade_data),
            )
        )

    equity = balance + floating_profit
    margin_free = equity - used_margin
    margin_level = None if used_margin <= 0.0 else (equity / used_margin) * 100.0
    account = BrokerAccountSnapshot(
        backend=BrokerBackend.CTRADER,
        account_id=str(session.account_id),
        balance=balance,
        equity=equity,
        margin_free=margin_free,
        trade_allowed=int(getattr(trader, "accessRights", 0) or 0) == 0,
        floating_profit=floating_profit,
        margin=used_margin,
        margin_level=margin_level,
    )

    snapshot_id = None
    if store is not None:
        snapshot_id = store.publish_broker_telemetry(
            account,
            tuple(positions),
            broker_name="FP Markets",
            environment="DEMO",
            connection_healthy=True,
        )
        _update_sampled_trajectory(store, tuple(positions))

    phase_text = str(phase or "AFTER").upper()
    print(
        "CTRADER_DEMO_ACCOUNT_PNL "
        f"phase={phase_text} balance={account.balance:.8g} equity={account.equity:.8g} "
        f"floating_pnl={float(account.floating_profit or 0.0):.8g} "
        f"margin={float(account.margin or 0.0):.8g} margin_free={float(account.margin_free or 0.0):.8g} "
        f"open_positions={len(positions)}"
    )
    for position in sorted(positions, key=lambda item: (item.symbol, item.position_id)):
        pnl_text = "NONE" if position.profit is None else f"{float(position.profit):.8g}"
        sl_text = "NONE" if position.stop_loss is None else f"{float(position.stop_loss):.8g}"
        tp_text = "NONE" if position.take_profit is None else f"{float(position.take_profit):.8g}"
        print(
            "CTRADER_DEMO_POSITION_PNL "
            f"phase={phase_text} symbol={position.symbol} position_id={position.position_id} "
            f"side={position.side} volume={position.volume:.8g} floating_pnl={pnl_text} "
            f"open_price={position.open_price:.8g} sl={sl_text} tp={tp_text}"
        )

    return DemoBrokerSnapshot(account, tuple(positions), snapshot_id)

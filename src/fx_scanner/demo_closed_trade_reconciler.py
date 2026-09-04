from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from .cli import _require_demo_autotrade_opt_in
from .config import load_project_config
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
HISTORY_LOOKBACK = timedelta(days=7)
HISTORY_MAX_ROWS = 1000
GEOMETRY_FIELDS = (
    "entry_mode",
    "pullback_atr",
    "zone_distance_atr",
    "confirmation",
    "fvg_age_minutes",
    "fvg_status",
    "fvg_fill_fraction",
    "chase_monitor_distance_atr",
    "exit_model",
)


@dataclass(frozen=True, slots=True)
class ClosedTradeReconcileReport:
    closing_deals: int
    matched_scanner_trades: int
    persisted: int
    duplicates: int
    partial_closes: int
    unmatched: int
    history_truncated: bool


class CTraderHistoryClient:
    """Small historical-data facade over the authenticated cTrader session."""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _message_types():
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOADealListReq,
            ProtoOAOrderListByPositionIdReq,
        )
        return ProtoOADealListReq, ProtoOAOrderListByPositionIdReq

    def recent_deals(self, *, from_timestamp_ms: int, to_timestamp_ms: int, max_rows: int):
        self.session.ensure_connected()
        DealListReq, _ = self._message_types()
        req = DealListReq()
        req.ctidTraderAccountId = int(self.session.account_id)
        req.fromTimestamp = int(from_timestamp_ms)
        req.toTimestamp = int(to_timestamp_ms)
        req.maxRows = int(max_rows)
        return self.session._send_sync(req, client_msg_id="demo-closed-deals")

    def orders_for_position(self, position_id: int):
        self.session.ensure_connected()
        _, OrderListByPositionIdReq = self._message_types()
        req = OrderListByPositionIdReq()
        req.ctidTraderAccountId = int(self.session.account_id)
        req.positionId = int(position_id)
        return self.session._send_sync(req, client_msg_id=f"demo-closed-orders-{int(position_id)}")

    def open_position_ids(self) -> set[int]:
        self.session.ensure_connected()
        reconcile = self.session.reconcile()
        return {
            int(getattr(position, "positionId", 0) or 0)
            for position in tuple(getattr(reconcile, "position", ()))
            if int(getattr(position, "positionId", 0) or 0) > 0
        }


def _has_field(message: Any, field: str) -> bool:
    checker = getattr(message, "HasField", None)
    if callable(checker):
        try:
            return bool(checker(field))
        except Exception:
            pass
    return getattr(message, field, None) is not None


def _money(value: Any, digits: Any) -> float:
    return float(value or 0) / (10 ** int(digits or 0))


def _as_signal_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return str(UUID(text))
    except (ValueError, TypeError, AttributeError):
        return None


def _signal_id_from_orders_or_deals(orders: tuple[Any, ...], deals: tuple[Any, ...]) -> str | None:
    for order in orders:
        signal_id = _as_signal_id(getattr(order, "clientOrderId", ""))
        if signal_id:
            return signal_id
    for deal in deals:
        comment = str(getattr(deal, "comment", "") or "")
        for token in reversed(comment.replace("/", ":").split(":")):
            signal_id = _as_signal_id(token)
            if signal_id:
                return signal_id
    return None


def _classify_exit(
    *,
    close_order: Any | None,
    signal: dict[str, Any],
    exit_price: float,
    gross_profit: float,
    partial: bool,
    structural_profit_protect: bool = False,
) -> str:
    if partial:
        if abs(gross_profit) <= 0.01:
            return "PARTIAL_CLOSE_BREAKEVEN"
        return "PARTIAL_CLOSE_PROFIT" if gross_profit > 0 else "PARTIAL_CLOSE_LOSS"
    if structural_profit_protect:
        if abs(gross_profit) <= 0.01:
            return "STRUCTURAL_PROTECT_BREAKEVEN"
        return "STRUCTURAL_PROTECT_PROFIT" if gross_profit > 0 else "STRUCTURAL_PROTECT_LOSS"
    if close_order is not None and bool(getattr(close_order, "isStopOut", False)):
        return "STOP_OUT"
    order_type = int(getattr(close_order, "orderType", 0) or 0) if close_order is not None else 0
    if order_type == 4:
        try:
            sl = float(signal["sl"])
            tp = float(signal["tp2"])
        except (KeyError, TypeError, ValueError):
            sl = tp = 0.0
        if sl > 0 and tp > 0 and exit_price > 0:
            return "SL_HIT" if abs(exit_price - sl) <= abs(exit_price - tp) else "TP_HIT"
        if abs(gross_profit) <= 0.01:
            return "PROTECTION_CLOSE_BREAKEVEN"
        return "TP_HIT" if gross_profit > 0 else "SL_HIT"
    if abs(gross_profit) <= 0.01:
        return "BREAKEVEN"
    return "MANUAL_CLOSE_PROFIT" if gross_profit > 0 else "MANUAL_CLOSE_LOSS"


class DemoClosedTradeReconciler:
    def __init__(self, *, history: CTraderHistoryClient, store, account_id: str):
        self.history = history
        self.store = store
        self.account_id = str(account_id)

    def _event_exists(self, event_key: str) -> bool:
        response = (
            self.store.client.table("broker_order_events")
            .select("id")
            .eq("backend", "CTRADER")
            .eq("account_id", self.account_id)
            .eq("broker_order_id", str(event_key))
            .limit(1)
            .execute()
        )
        return bool(response.data or [])

    def _profit_protect_exit(self, *, signal_id: str, position_id: int) -> bool:
        """Return true only for the exact scanner-linked confirmed protector exit."""
        response = (
            self.store.client.table("broker_order_events")
            .select("id")
            .eq("backend", "CTRADER")
            .eq("account_id", self.account_id)
            .eq("signal_key", signal_id)
            .eq("event_type", "DEMO_STRUCTURAL_PROFIT_PROTECT_EXIT")
            .eq("broker_order_id", f"PROFIT_PROTECT:{int(position_id)}")
            .eq("accepted", True)
            .limit(2)
            .execute()
        )
        rows = list(response.data or [])
        return len(rows) == 1

    def _signal(self, signal_id: str) -> dict[str, Any] | None:
        response = (
            self.store.client.table("signals")
            .select(
                "id,run_id,observed_at,symbol,direction,setup_type,final_score,"
                "entry_low,entry_high,sl,tp2,rr2"
            )
            .eq("id", signal_id)
            .limit(2)
            .execute()
        )
        rows = list(response.data or [])
        return dict(rows[0]) if len(rows) == 1 else None

    def _geometry(self, signal_id: str) -> dict[str, Any]:
        """Read latest exact producer geometry for this signal, if available."""
        response = (
            self.store.client.table("broker_order_events")
            .select("payload")
            .eq("backend", "CTRADER")
            .eq("account_id", self.account_id)
            .eq("signal_key", signal_id)
            .eq("event_type", "DEMO_SIGNAL_GEOMETRY")
            .order("observed_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = list(response.data or [])
        if not rows or not isinstance(rows[0].get("payload"), dict):
            return {}
        payload = dict(rows[0]["payload"])
        return {key: payload.get(key) for key in GEOMETRY_FIELDS if key in payload}

    def run_once(self, *, now: datetime | None = None) -> ClosedTradeReconcileReport:
        now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        start = now - HISTORY_LOOKBACK
        deals_res = self.history.recent_deals(
            from_timestamp_ms=int(start.timestamp() * 1000),
            to_timestamp_ms=int(now.timestamp() * 1000),
            max_rows=HISTORY_MAX_ROWS,
        )
        deals = tuple(getattr(deals_res, "deal", ()))
        closing_deals = tuple(
            deal for deal in deals
            if _has_field(deal, "closePositionDetail")
            and int(getattr(deal, "dealStatus", 0) or 0) in {2, 3}
        )
        open_position_ids = self.history.open_position_ids()
        grouped: dict[int, tuple[Any, ...]] = {}
        for deal in deals:
            position_id = int(getattr(deal, "positionId", 0) or 0)
            if position_id > 0:
                grouped[position_id] = grouped.get(position_id, ()) + (deal,)

        matched = persisted = duplicates = partial_closes = unmatched = 0
        for close_deal in sorted(closing_deals, key=lambda item: int(getattr(item, "executionTimestamp", 0) or 0)):
            deal_id = int(getattr(close_deal, "dealId", 0) or 0)
            position_id = int(getattr(close_deal, "positionId", 0) or 0)
            closing_order_id = int(getattr(close_deal, "orderId", 0) or 0)
            if deal_id <= 0 or position_id <= 0:
                unmatched += 1
                continue
            event_key = f"DEAL:{deal_id}"
            if self._event_exists(event_key):
                duplicates += 1
                continue

            orders_res = self.history.orders_for_position(position_id)
            orders = tuple(getattr(orders_res, "order", ()))
            position_deals = grouped.get(position_id, ())
            signal_id = _signal_id_from_orders_or_deals(orders, position_deals)
            if signal_id is None:
                unmatched += 1
                continue
            signal = self._signal(signal_id)
            if signal is None:
                unmatched += 1
                continue
            geometry = self._geometry(signal_id)
            matched += 1

            close_order = next(
                (order for order in orders if int(getattr(order, "orderId", 0) or 0) == closing_order_id),
                None,
            )
            detail = getattr(close_deal, "closePositionDetail")
            digits = int(getattr(detail, "moneyDigits", 0) or 0)
            gross_profit = _money(getattr(detail, "grossProfit", 0), digits)
            swap = _money(getattr(detail, "swap", 0), digits)
            commission = _money(getattr(detail, "commission", 0), digits)
            pnl_conversion_fee = _money(getattr(detail, "pnlConversionFee", 0), digits)
            net_pnl_estimate = gross_profit + swap + commission - pnl_conversion_fee
            exit_price = float(getattr(close_deal, "executionPrice", 0.0) or 0.0)
            execution_ms = int(getattr(close_deal, "executionTimestamp", 0) or 0)
            exit_time = datetime.fromtimestamp(execution_ms / 1000.0, tz=UTC) if execution_ms > 0 else now
            partial = position_id in open_position_ids
            if partial:
                partial_closes += 1
            structural_profit_protect = bool(
                not partial
                and self._profit_protect_exit(signal_id=signal_id, position_id=position_id)
            )

            outcome = _classify_exit(
                close_order=close_order,
                signal=signal,
                exit_price=exit_price,
                gross_profit=gross_profit,
                partial=partial,
                structural_profit_protect=structural_profit_protect,
            )
            event_type = "DEMO_TRADE_PARTIAL_CLOSE" if partial else "DEMO_TRADE_CLOSED"
            payload = {
                "signal_id": signal_id,
                "run_id": signal.get("run_id"),
                "symbol": signal.get("symbol"),
                "direction": signal.get("direction"),
                "setup_type": signal.get("setup_type"),
                "final_score": signal.get("final_score"),
                "rr2": signal.get("rr2"),
                "entry_low": signal.get("entry_low"),
                "entry_high": signal.get("entry_high"),
                "planned_sl": signal.get("sl"),
                "planned_tp2": signal.get("tp2"),
                "position_id": str(position_id),
                "closing_order_id": str(closing_order_id),
                "closing_deal_id": str(deal_id),
                "exit_time": exit_time.isoformat(),
                "exit_price": exit_price,
                "exit_type": outcome,
                "partial_close": partial,
                "gross_profit": gross_profit,
                "swap": swap,
                "commission": commission,
                "pnl_conversion_fee": pnl_conversion_fee,
                "net_pnl_estimate": net_pnl_estimate,
                "money_digits": digits,
                "close_order_type": None if close_order is None else int(getattr(close_order, "orderType", 0) or 0),
                "is_stop_out": bool(getattr(close_order, "isStopOut", False)) if close_order is not None else False,
                "source": "CTRADER_DEAL_HISTORY",
                "entry_geometry_available": bool(geometry),
                "trade_management_exit": "STRUCTURAL_PROFIT_PROTECT" if structural_profit_protect else None,
                "exit_attribution": "DEMO_STRUCTURAL_PROFIT_PROTECT_EXIT" if structural_profit_protect else None,
            }
            payload.update(geometry)
            self.store.record_order_event(
                backend="CTRADER",
                account_id=self.account_id,
                signal_key=signal_id,
                event_type=event_type,
                broker_order_id=event_key,
                accepted=True,
                code=outcome,
                message="cTrader closed deal reconciled",
                payload=payload,
            )
            persisted += 1
            print(
                "CTRADER_DEMO_TRADE_OUTCOME "
                f"signal_id={signal_id} symbol={signal.get('symbol')} "
                f"position_id={position_id} deal_id={deal_id} outcome={outcome} "
                f"gross_profit={gross_profit:.8g} net_pnl_estimate={net_pnl_estimate:.8g} "
                f"exit_price={exit_price:.8g} partial={int(partial)} "
                f"profit_protect={int(structural_profit_protect)} "
                f"entry_mode={geometry.get('entry_mode', 'LEGACY')}"
            )

        return ClosedTradeReconcileReport(
            closing_deals=len(closing_deals),
            matched_scanner_trades=matched,
            persisted=persisted,
            duplicates=duplicates,
            partial_closes=partial_closes,
            unmatched=unmatched,
            history_truncated=bool(getattr(deals_res, "hasMore", False)),
        )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    _require_demo_autotrade_opt_in(policy)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_CLOSED_TRADE_RECONCILER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_CLOSED_TRADE_RECONCILER_REQUIRE_DEMO")
    symbols = [pair.symbol for pair in cfg.pairs]
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    history = CTraderHistoryClient(session)
    reconciler = DemoClosedTradeReconciler(history=history, store=store, account_id=str(session.account_id))
    try:
        report = reconciler.run_once()
        store.write_heartbeat(
            "ctrader_demo_closed_trade_reconciler",
            healthy=not report.history_truncated,
            lag_seconds=0.0,
            details={
                "lookback_days": HISTORY_LOOKBACK.days,
                "closing_deals": report.closing_deals,
                "matched_scanner_trades": report.matched_scanner_trades,
                "persisted": report.persisted,
                "duplicates": report.duplicates,
                "partial_closes": report.partial_closes,
                "unmatched": report.unmatched,
                "history_truncated": report.history_truncated,
                "outcome_event": "DEMO_TRADE_CLOSED",
                "entry_geometry_enrichment": "DEMO_SIGNAL_GEOMETRY",
                "trade_management_attribution": "DEMO_STRUCTURAL_PROFIT_PROTECT_EXIT",
            },
        )
        print(
            "CTRADER_DEMO_CLOSED_TRADE_RECONCILE_OK "
            f"lookback_days={HISTORY_LOOKBACK.days} closing_deals={report.closing_deals} "
            f"matched={report.matched_scanner_trades} persisted={report.persisted} "
            f"duplicates={report.duplicates} partial={report.partial_closes} "
            f"unmatched={report.unmatched} truncated={int(report.history_truncated)}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

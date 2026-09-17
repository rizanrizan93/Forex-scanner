from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import load_project_config
from .demo_closed_trade_reconciler import (
    CTraderHistoryClient,
    DemoClosedTradeReconciler,
    GEOMETRY_FIELDS,
    HISTORY_LOOKBACK,
    HISTORY_MAX_ROWS,
    _classify_exit,
    _has_field,
    _money,
    _signal_id_from_orders_or_deals,
)
from .execution.factory import build_broker_gateway
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
RAW_EVENT_TYPE = "DEMO_BROKER_CLOSED_DEAL_RAW"
RAW_EVENT_PREFIX = "BROKER_TRUTH:DEAL:"
RAW_SIGNAL_PREFIX = "BROKER_TRUTH:POSITION:"
LINEAGE_EVENT_TYPE = "ORDER_ACCEPTED"
LINEAGE_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class BrokerTruthReconcileReport:
    closing_deals: int
    raw_persisted: int
    raw_duplicates: int
    matched_scanner_trades: int
    reconstructed: int
    reconstructed_duplicates: int
    partial_closes: int
    unattributed: int
    history_truncated: bool


class DeepCTraderHistoryClient(CTraderHistoryClient):
    """Read-only cTrader history client with complete per-position deal lookup."""

    @staticmethod
    def _position_deal_message_type():
        from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOADealListByPositionIdReq

        return ProtoOADealListByPositionIdReq

    def deals_for_position(self, position_id: int, *, to_timestamp_ms: int):
        self.session.ensure_connected()
        DealListByPositionIdReq = self._position_deal_message_type()
        req = DealListByPositionIdReq()
        req.ctidTraderAccountId = int(self.session.account_id)
        req.positionId = int(position_id)
        req.fromTimestamp = 0
        req.toTimestamp = int(to_timestamp_ms)
        return self.session._send_sync(
            req,
            client_msg_id=f"demo-broker-truth-deals-{int(position_id)}",
        )


class DemoBrokerTruthReconciler(DemoClosedTradeReconciler):
    """Persist broker truth first; reconstruct calibration outcomes only with exact lineage.

    Raw cTrader closing deals are observational evidence. They are deliberately
    stored under a distinct event type/key namespace, so they can never be
    mistaken for scanner trade outcomes. A normal DEMO_TRADE_CLOSED event is
    created only when a unique scanner signal UUID can be recovered and the
    canonical signal row still exists.
    """

    history: DeepCTraderHistoryClient

    def _raw_event_exists(self, raw_event_key: str) -> bool:
        response = (
            self.store.client.table("broker_order_events")
            .select("id")
            .eq("backend", "CTRADER")
            .eq("account_id", self.account_id)
            .eq("event_type", RAW_EVENT_TYPE)
            .eq("broker_order_id", raw_event_key)
            .limit(1)
            .execute()
        )
        return bool(response.data or [])

    def _durable_position_lineage(self) -> tuple[dict[int, str], set[int]]:
        """Return unique position->signal lineage and explicitly ambiguous positions.

        Account ID is intentionally not part of this join because historical
        cTrader telemetry has used both visible-login and native account aliases.
        Position ID plus a unique accepted scanner signal is required. Conflicts
        are quarantined instead of guessed.
        """
        response = (
            self.store.client.table("broker_order_events")
            .select("signal_key,payload,observed_at")
            .eq("backend", "CTRADER")
            .eq("event_type", LINEAGE_EVENT_TYPE)
            .eq("accepted", True)
            .order("observed_at", desc=True)
            .limit(LINEAGE_LIMIT)
            .execute()
        )
        candidates: dict[int, set[str]] = {}
        for row in response.data or []:
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            raw_position_id = payload.get("broker_position_id")
            try:
                position_id = int(raw_position_id)
            except (TypeError, ValueError):
                continue
            if position_id <= 0:
                continue
            signal_id = _signal_id_from_orders_or_deals(
                (type("LineageOrder", (), {"clientOrderId": row.get("signal_key")})(),),
                (),
            )
            if signal_id is None:
                signal_id = _signal_id_from_orders_or_deals(
                    (type("LineageOrder", (), {"clientOrderId": payload.get("signal_id")})(),),
                    (),
                )
            if signal_id is None:
                continue
            candidates.setdefault(position_id, set()).add(signal_id)

        resolved: dict[int, str] = {}
        ambiguous: set[int] = set()
        for position_id, signal_ids in candidates.items():
            if len(signal_ids) == 1:
                resolved[position_id] = next(iter(signal_ids))
            elif len(signal_ids) > 1:
                ambiguous.add(position_id)
        return resolved, ambiguous

    @staticmethod
    def _partial_state(
        position_deals: tuple[Any, ...],
        *,
        closing_deal_id: int,
        currently_open: bool,
    ) -> tuple[bool, bool, int | None]:
        """Reconstruct remaining volume at the target close from complete position deals.

        Returns (partial_close, reconstruction_reliable, remaining_volume_cents).
        When full per-position history is insufficient, fall back to the broker's
        current open-position state but mark the reconstruction as not reliable.
        """
        running_volume = 0
        saw_open_volume = False
        ordered = sorted(
            position_deals,
            key=lambda item: (
                int(getattr(item, "executionTimestamp", 0) or 0),
                int(getattr(item, "dealId", 0) or 0),
            ),
        )
        for deal in ordered:
            deal_id = int(getattr(deal, "dealId", 0) or 0)
            deal_volume = int(getattr(deal, "volume", 0) or 0)
            if _has_field(deal, "closePositionDetail"):
                detail = getattr(deal, "closePositionDetail")
                closed_volume = int(getattr(detail, "closedVolume", 0) or 0)
                if closed_volume <= 0:
                    closed_volume = deal_volume
                running_volume = max(0, running_volume - max(0, closed_volume))
            else:
                if deal_volume > 0:
                    saw_open_volume = True
                    running_volume += deal_volume
            if deal_id == closing_deal_id:
                if saw_open_volume:
                    return running_volume > 0, True, running_volume
                return bool(currently_open), False, None
        return bool(currently_open), False, None

    @staticmethod
    def _raw_close_payload(
        close_deal: Any,
        *,
        position_id: int,
        deal_id: int,
        closing_order_id: int,
        exit_time: datetime,
        partial: bool,
        partial_reconstruction_reliable: bool,
        remaining_volume_cents: int | None,
        signal_candidate_id: str | None,
        attribution_method: str,
        lineage_ambiguous: bool,
    ) -> dict[str, Any]:
        detail = getattr(close_deal, "closePositionDetail")
        digits = int(getattr(detail, "moneyDigits", 0) or 0)
        gross_profit = _money(getattr(detail, "grossProfit", 0), digits)
        swap = _money(getattr(detail, "swap", 0), digits)
        commission = _money(getattr(detail, "commission", 0), digits)
        pnl_conversion_fee = _money(getattr(detail, "pnlConversionFee", 0), digits)
        return {
            "source": "CTRADER_DEAL_HISTORY_RAW",
            "broker_truth": True,
            "calibration_eligible": False,
            "signal_candidate_id": signal_candidate_id,
            "attribution_method": attribution_method,
            "lineage_ambiguous": bool(lineage_ambiguous),
            "position_id": str(position_id),
            "closing_order_id": str(closing_order_id),
            "closing_deal_id": str(deal_id),
            "execution_timestamp_ms": int(getattr(close_deal, "executionTimestamp", 0) or 0),
            "exit_time": exit_time.isoformat(),
            "exit_price": float(getattr(close_deal, "executionPrice", 0.0) or 0.0),
            "symbol_id": int(getattr(close_deal, "symbolId", 0) or 0),
            "trade_side": int(getattr(close_deal, "tradeSide", 0) or 0),
            "deal_status": int(getattr(close_deal, "dealStatus", 0) or 0),
            "deal_type": int(getattr(close_deal, "dealType", 0) or 0),
            "deal_volume_cents": int(getattr(close_deal, "volume", 0) or 0),
            "entry_price": float(getattr(detail, "entryPrice", 0.0) or 0.0),
            "closed_volume_cents": int(getattr(detail, "closedVolume", 0) or 0),
            "remaining_volume_cents": remaining_volume_cents,
            "partial_close": bool(partial),
            "partial_reconstruction_reliable": bool(partial_reconstruction_reliable),
            "gross_profit": gross_profit,
            "swap": swap,
            "commission": commission,
            "pnl_conversion_fee": pnl_conversion_fee,
            "net_pnl_estimate": gross_profit + swap + commission - pnl_conversion_fee,
            "balance_after_close": _money(getattr(detail, "balance", 0), digits),
            "money_digits": digits,
            "label": str(getattr(close_deal, "label", "") or ""),
            "comment": str(getattr(close_deal, "comment", "") or ""),
        }

    def _persist_reconstructed_outcome(
        self,
        *,
        close_deal: Any,
        orders: tuple[Any, ...],
        signal_id: str,
        signal: dict[str, Any],
        position_id: int,
        deal_id: int,
        closing_order_id: int,
        partial: bool,
        exit_time: datetime,
        attribution_method: str,
        raw_event_key: str,
    ) -> None:
        close_order = next(
            (
                order
                for order in orders
                if int(getattr(order, "orderId", 0) or 0) == closing_order_id
            ),
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
        geometry = self._geometry(signal_id)
        structural_profit_protect = bool(
            not partial
            and self._profit_protect_exit(signal_id=signal_id, position_id=position_id)
        )
        adaptive_profit_lock = bool(
            not partial
            and not structural_profit_protect
            and self._adaptive_profit_lock_exit(signal_id=signal_id, position_id=position_id)
        )
        outcome = _classify_exit(
            close_order=close_order,
            signal=signal,
            exit_price=exit_price,
            gross_profit=gross_profit,
            partial=partial,
            structural_profit_protect=structural_profit_protect,
            adaptive_profit_lock=adaptive_profit_lock,
            realized_pnl=net_pnl_estimate,
        )
        if structural_profit_protect:
            trade_management_exit = "STRUCTURAL_PROFIT_PROTECT"
            exit_attribution = "DEMO_STRUCTURAL_PROFIT_PROTECT_EXIT"
        elif adaptive_profit_lock:
            trade_management_exit = "ADAPTIVE_PROFIT_LOCK"
            exit_attribution = "DEMO_ADAPTIVE_PROFIT_LOCK_ADVANCED"
        else:
            trade_management_exit = None
            exit_attribution = None

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
            "partial_close": bool(partial),
            "gross_profit": gross_profit,
            "swap": swap,
            "commission": commission,
            "pnl_conversion_fee": pnl_conversion_fee,
            "net_pnl_estimate": net_pnl_estimate,
            "money_digits": digits,
            "close_order_type": (
                None
                if close_order is None
                else int(getattr(close_order, "orderType", 0) or 0)
            ),
            "is_stop_out": (
                bool(getattr(close_order, "isStopOut", False))
                if close_order is not None
                else False
            ),
            "source": "CTRADER_DEAL_HISTORY_RECONSTRUCTED",
            "entry_geometry_available": bool(geometry),
            "trade_management_exit": trade_management_exit,
            "exit_attribution": exit_attribution,
            "reconstruction_attribution_method": attribution_method,
            "broker_truth_event_key": raw_event_key,
            "calibration_eligible": True,
        }
        payload.update({key: geometry.get(key) for key in GEOMETRY_FIELDS if key in geometry})
        self.store.record_order_event(
            backend="CTRADER",
            account_id=self.account_id,
            signal_key=signal_id,
            event_type="DEMO_TRADE_PARTIAL_CLOSE" if partial else "DEMO_TRADE_CLOSED",
            broker_order_id=f"DEAL:{deal_id}",
            accepted=True,
            code=outcome,
            message="cTrader closed deal reconstructed from durable broker truth",
            payload=payload,
        )

    def run_once(self, *, now: datetime | None = None) -> BrokerTruthReconcileReport:
        now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        start = now - HISTORY_LOOKBACK
        deals_res = self.history.recent_deals(
            from_timestamp_ms=int(start.timestamp() * 1000),
            to_timestamp_ms=int(now.timestamp() * 1000),
            max_rows=HISTORY_MAX_ROWS,
        )
        deals = tuple(getattr(deals_res, "deal", ()))
        closing_deals = tuple(
            deal
            for deal in deals
            if _has_field(deal, "closePositionDetail")
            and int(getattr(deal, "dealStatus", 0) or 0) in {2, 3}
        )
        open_position_ids = self.history.open_position_ids()
        durable_lineage, ambiguous_positions = self._durable_position_lineage()

        raw_persisted = 0
        raw_duplicates = 0
        matched = 0
        reconstructed = 0
        reconstructed_duplicates = 0
        partial_closes = 0
        unattributed = 0

        position_cache: dict[int, tuple[Any, ...]] = {}
        order_cache: dict[int, tuple[Any, ...]] = {}

        for close_deal in sorted(
            closing_deals,
            key=lambda item: int(getattr(item, "executionTimestamp", 0) or 0),
        ):
            deal_id = int(getattr(close_deal, "dealId", 0) or 0)
            position_id = int(getattr(close_deal, "positionId", 0) or 0)
            closing_order_id = int(getattr(close_deal, "orderId", 0) or 0)
            if deal_id <= 0 or position_id <= 0:
                unattributed += 1
                continue

            if position_id not in position_cache:
                position_res = self.history.deals_for_position(
                    position_id,
                    to_timestamp_ms=int(now.timestamp() * 1000),
                )
                position_cache[position_id] = tuple(getattr(position_res, "deal", ()))
            position_deals = position_cache[position_id]

            if position_id not in order_cache:
                orders_res = self.history.orders_for_position(position_id)
                order_cache[position_id] = tuple(getattr(orders_res, "order", ()))
            orders = order_cache[position_id]

            broker_signal_id = _signal_id_from_orders_or_deals(orders, position_deals)
            lineage_ambiguous = position_id in ambiguous_positions
            if broker_signal_id is not None:
                signal_candidate_id = broker_signal_id
                attribution_method = "BROKER_ORDER_OR_DEAL_UUID"
            elif not lineage_ambiguous and position_id in durable_lineage:
                signal_candidate_id = durable_lineage[position_id]
                attribution_method = "DURABLE_ORDER_ACCEPTED_POSITION_ID"
            elif lineage_ambiguous:
                signal_candidate_id = None
                attribution_method = "AMBIGUOUS_DURABLE_LINEAGE"
            else:
                signal_candidate_id = None
                attribution_method = "UNATTRIBUTED_BROKER_DEAL"

            partial, partial_reliable, remaining_volume = self._partial_state(
                position_deals,
                closing_deal_id=deal_id,
                currently_open=position_id in open_position_ids,
            )
            if partial:
                partial_closes += 1

            execution_ms = int(getattr(close_deal, "executionTimestamp", 0) or 0)
            exit_time = (
                datetime.fromtimestamp(execution_ms / 1000.0, tz=UTC)
                if execution_ms > 0
                else now
            )
            raw_event_key = f"{RAW_EVENT_PREFIX}{deal_id}"
            raw_signal_key = signal_candidate_id or f"{RAW_SIGNAL_PREFIX}{position_id}"
            raw_payload = self._raw_close_payload(
                close_deal,
                position_id=position_id,
                deal_id=deal_id,
                closing_order_id=closing_order_id,
                exit_time=exit_time,
                partial=partial,
                partial_reconstruction_reliable=partial_reliable,
                remaining_volume_cents=remaining_volume,
                signal_candidate_id=signal_candidate_id,
                attribution_method=attribution_method,
                lineage_ambiguous=lineage_ambiguous,
            )
            if self._raw_event_exists(raw_event_key):
                raw_duplicates += 1
            else:
                self.store.record_order_event(
                    backend="CTRADER",
                    account_id=self.account_id,
                    signal_key=raw_signal_key,
                    event_type=RAW_EVENT_TYPE,
                    broker_order_id=raw_event_key,
                    accepted=None,
                    code=attribution_method,
                    message="raw cTrader closing deal captured; not calibration eligible",
                    payload=raw_payload,
                )
                raw_persisted += 1

            if signal_candidate_id is None:
                unattributed += 1
                continue
            signal = self._signal(signal_candidate_id)
            if signal is None:
                unattributed += 1
                continue
            matched += 1

            event_key = f"DEAL:{deal_id}"
            if self._event_exists(event_key):
                reconstructed_duplicates += 1
                continue
            self._persist_reconstructed_outcome(
                close_deal=close_deal,
                orders=orders,
                signal_id=signal_candidate_id,
                signal=signal,
                position_id=position_id,
                deal_id=deal_id,
                closing_order_id=closing_order_id,
                partial=partial,
                exit_time=exit_time,
                attribution_method=attribution_method,
                raw_event_key=raw_event_key,
            )
            reconstructed += 1

        return BrokerTruthReconcileReport(
            closing_deals=len(closing_deals),
            raw_persisted=raw_persisted,
            raw_duplicates=raw_duplicates,
            matched_scanner_trades=matched,
            reconstructed=reconstructed,
            reconstructed_duplicates=reconstructed_duplicates,
            partial_closes=partial_closes,
            unattributed=unattributed,
            history_truncated=bool(getattr(deals_res, "hasMore", False)),
        )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_BROKER_TRUTH_RECONCILER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_BROKER_TRUTH_RECONCILER_REQUIRE_DEMO")

    symbols = [pair.symbol for pair in cfg.pairs]
    _gateway, session = build_broker_gateway(policy, symbols, backend="CTRADER")
    store = SupabaseOperationalStore.from_env()
    history = DeepCTraderHistoryClient(session)
    reconciler = DemoBrokerTruthReconciler(
        history=history,
        store=store,
        account_id=str(session.account_id),
    )
    try:
        report = reconciler.run_once()
        store.write_heartbeat(
            "ctrader_demo_broker_truth_reconciler",
            healthy=not report.history_truncated,
            lag_seconds=0.0,
            details={
                "lookback_days": HISTORY_LOOKBACK.days,
                "closing_deals": report.closing_deals,
                "raw_event_type": RAW_EVENT_TYPE,
                "raw_persisted": report.raw_persisted,
                "raw_duplicates": report.raw_duplicates,
                "matched_scanner_trades": report.matched_scanner_trades,
                "reconstructed": report.reconstructed,
                "reconstructed_duplicates": report.reconstructed_duplicates,
                "partial_closes": report.partial_closes,
                "unattributed": report.unattributed,
                "history_truncated": report.history_truncated,
                "raw_calibration_eligible": False,
                "reconstruction_gate": "UNIQUE_SIGNAL_UUID_AND_CANONICAL_SIGNAL_ROW",
            },
        )
        print(
            "CTRADER_DEMO_BROKER_TRUTH_RECONCILE_OK "
            f"closing_deals={report.closing_deals} raw_persisted={report.raw_persisted} "
            f"raw_duplicates={report.raw_duplicates} matched={report.matched_scanner_trades} "
            f"reconstructed={report.reconstructed} "
            f"reconstructed_duplicates={report.reconstructed_duplicates} "
            f"partial={report.partial_closes} unattributed={report.unattributed} "
            f"truncated={int(report.history_truncated)}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

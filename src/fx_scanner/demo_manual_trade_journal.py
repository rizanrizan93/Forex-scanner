from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from .config import load_project_config
from .demo_closed_trade_reconciler import CTraderHistoryClient, _signal_id_from_orders_or_deals
from .exceptions import ConfigurationError
from .execution.ctrader_session import CTraderOpenApiSession
from .execution.ctrader_tokens import CTraderTokenStateStore
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
HISTORY_LOOKBACK = timedelta(days=7)
HISTORY_MAX_ROWS = 2000
WORKER_NAME = "ctrader_demo_manual_trade_journal"
XAU_RESEARCH_TRACK = "TELEGRAM_XAU_RECONSTRUCTION"
XAU_CANDIDATE_STRATEGY = "XAU_M15_LIQUIDITY_SWEEP_FADE_V1"


@dataclass(frozen=True, slots=True)
class ManualTradeJournalReport:
    deals: int
    positions: int
    manual_positions: int
    scanner_positions: int
    opening_events: int
    partial_close_events: int
    closed_events: int
    duplicates: int
    skipped_order_lookup: int
    unresolved_symbol: int
    history_truncated: bool


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _has_field(message: Any, field: str) -> bool:
    checker = getattr(message, "HasField", None)
    if callable(checker):
        try:
            return bool(checker(field))
        except Exception:
            pass
    return getattr(message, field, None) is not None


def _is_close_deal(deal: Any) -> bool:
    return _has_field(deal, "closePositionDetail")


def _deal_time(deal: Any) -> datetime | None:
    raw = int(getattr(deal, "executionTimestamp", 0) or 0)
    if raw <= 0:
        return None
    return datetime.fromtimestamp(raw / 1000.0, tz=UTC)


def _deal_side(deal: Any) -> str | None:
    code = int(getattr(deal, "tradeSide", 0) or 0)
    return "BUY" if code == 1 else "SELL" if code == 2 else None


def _opposite(side: str | None) -> str | None:
    return "SELL" if side == "BUY" else "BUY" if side == "SELL" else None


def _position_direction(deals: tuple[Any, ...]) -> str | None:
    ordered = sorted(deals, key=lambda item: int(getattr(item, "executionTimestamp", 0) or 0))
    for deal in ordered:
        if not _is_close_deal(deal):
            side = _deal_side(deal)
            if side:
                return side
    for deal in ordered:
        if _is_close_deal(deal):
            return _opposite(_deal_side(deal))
    return None


def _position_symbol(deals: tuple[Any, ...], session) -> tuple[str | None, int | None]:
    for deal in deals:
        symbol_id = int(getattr(deal, "symbolId", 0) or 0)
        if symbol_id <= 0:
            continue
        symbol = str(getattr(session, "symbol_name_by_id", {}).get(symbol_id, "") or "").upper().strip()
        return (symbol or None), symbol_id
    return None, None


def _raw_volume(deal: Any) -> float:
    try:
        value = float(getattr(deal, "volume", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if isfinite(value) and value >= 0.0 else 0.0


def _volume_lots(deal: Any, *, symbol_id: int | None, session) -> float | None:
    raw = _raw_volume(deal)
    if raw <= 0.0:
        return None
    info = None if symbol_id is None else getattr(session, "symbol_full_by_id", {}).get(symbol_id)
    lot_size = int(getattr(info, "lotSize", 0) or 0) if info is not None else 0
    if lot_size <= 0:
        return None
    value = raw / float(lot_size)
    return value if isfinite(value) and value >= 0.0 else None


def _weighted_entry_price(deals: tuple[Any, ...]) -> float | None:
    weighted = 0.0
    volume = 0.0
    for deal in deals:
        if _is_close_deal(deal):
            continue
        raw_volume = _raw_volume(deal)
        try:
            price = float(getattr(deal, "executionPrice", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if raw_volume <= 0.0 or not isfinite(price) or price <= 0.0:
            continue
        weighted += raw_volume * price
        volume += raw_volume
    return weighted / volume if volume > 0.0 else None


def _money(value: Any, digits: Any) -> float:
    return float(value or 0) / (10 ** int(digits or 0))


def _close_financials(deal: Any) -> dict[str, float | int]:
    detail = getattr(deal, "closePositionDetail", None)
    if detail is None:
        return {}
    digits = int(getattr(detail, "moneyDigits", 0) or 0)
    gross = _money(getattr(detail, "grossProfit", 0), digits)
    swap = _money(getattr(detail, "swap", 0), digits)
    commission = _money(getattr(detail, "commission", 0), digits)
    conversion_fee = _money(getattr(detail, "pnlConversionFee", 0), digits)
    return {
        "money_digits": digits,
        "gross_profit": gross,
        "swap": swap,
        "commission": commission,
        "pnl_conversion_fee": conversion_fee,
        "net_pnl_estimate": gross + swap + commission - conversion_fee,
    }


def _manual_close_type(close_order: Any | None, *, net_pnl: float, partial: bool) -> str:
    if partial:
        if abs(net_pnl) <= 0.01:
            return "PARTIAL_CLOSE_BREAKEVEN"
        return "PARTIAL_CLOSE_PROFIT" if net_pnl > 0 else "PARTIAL_CLOSE_LOSS"
    if close_order is not None and bool(getattr(close_order, "isStopOut", False)):
        return "STOP_OUT"
    order_type = int(getattr(close_order, "orderType", 0) or 0) if close_order is not None else 0
    if order_type == 4:
        if abs(net_pnl) <= 0.01:
            return "SERVER_PROTECTION_BREAKEVEN"
        return "SERVER_PROTECTION_PROFIT" if net_pnl > 0 else "SERVER_PROTECTION_LOSS"
    if abs(net_pnl) <= 0.01:
        return "MANUAL_CLOSE_BREAKEVEN"
    return "MANUAL_CLOSE_PROFIT" if net_pnl > 0 else "MANUAL_CLOSE_LOSS"


class DemoManualTradeJournal:
    """Durably journal broker deals that are not linked to scanner signal UUIDs.

    The journal never places, amends or closes an order.  It reads cTrader deal
    and order history, separates scanner-linked positions from manual positions,
    and writes deterministic research events to ``broker_order_events``.
    """

    def __init__(self, *, history: CTraderHistoryClient, store, session, account_id: str):
        self.history = history
        self.store = store
        self.session = session
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

    def _scanner_signal_exists(self, signal_id: str) -> bool:
        response = (
            self.store.client.table("signals")
            .select("id")
            .eq("id", str(signal_id))
            .limit(1)
            .execute()
        )
        return bool(response.data or [])

    def _record(self, *, event_key: str, position_id: int, event_type: str, code: str, payload: dict[str, Any]) -> bool:
        if self._event_exists(event_key):
            return False
        self.store.record_order_event(
            backend="CTRADER",
            account_id=self.account_id,
            signal_key=f"MANUAL:CTRADER:{int(position_id)}",
            event_type=event_type,
            broker_order_id=event_key,
            accepted=True,
            code=code,
            message="cTrader manual DEMO trade journal evidence",
            payload=payload,
        )
        return True

    def run_once(self, *, now: datetime | None = None) -> ManualTradeJournalReport:
        now = (now or datetime.now(tz=UTC)).astimezone(UTC)
        start = now - HISTORY_LOOKBACK
        deals_res = self.history.recent_deals(
            from_timestamp_ms=int(start.timestamp() * 1000),
            to_timestamp_ms=int(now.timestamp() * 1000),
            max_rows=HISTORY_MAX_ROWS,
        )
        accepted_deals = tuple(
            deal
            for deal in tuple(getattr(deals_res, "deal", ()))
            if int(getattr(deal, "positionId", 0) or 0) > 0
            and int(getattr(deal, "dealId", 0) or 0) > 0
            and int(getattr(deal, "dealStatus", 0) or 0) in {2, 3}
        )
        grouped: dict[int, list[Any]] = {}
        for deal in accepted_deals:
            grouped.setdefault(int(getattr(deal, "positionId", 0) or 0), []).append(deal)

        open_ids = self.history.open_position_ids()
        manual_positions = scanner_positions = 0
        opening_events = partial_events = closed_events = duplicates = 0
        skipped_order_lookup = unresolved_symbol = 0

        for position_id, raw_group in sorted(grouped.items()):
            group = tuple(sorted(raw_group, key=lambda item: int(getattr(item, "executionTimestamp", 0) or 0)))
            try:
                orders_res = self.history.orders_for_position(position_id)
                orders = tuple(getattr(orders_res, "order", ()))
            except Exception as exc:
                skipped_order_lookup += 1
                print(
                    "CTRADER_DEMO_MANUAL_JOURNAL_SKIP "
                    f"position_id={position_id} reason=ORDER_HISTORY_UNAVAILABLE error={type(exc).__name__}"
                )
                continue

            candidate_signal_id = _signal_id_from_orders_or_deals(orders, group)
            if candidate_signal_id and self._scanner_signal_exists(candidate_signal_id):
                scanner_positions += 1
                continue

            manual_positions += 1
            symbol, symbol_id = _position_symbol(group, self.session)
            if symbol is None:
                unresolved_symbol += 1
                symbol = f"SYMBOL_ID_{symbol_id or 0}"
            direction = _position_direction(group)
            entry_price = _weighted_entry_price(group)
            opening_deals = tuple(deal for deal in group if not _is_close_deal(deal))
            closing_deals = tuple(deal for deal in group if _is_close_deal(deal))
            opened_at = _deal_time(opening_deals[0]) if opening_deals else None
            initial_volume_lots = sum(
                value
                for value in (
                    _volume_lots(deal, symbol_id=symbol_id, session=self.session)
                    for deal in opening_deals
                )
                if value is not None
            )
            if not opening_deals:
                initial_volume_lots = 0.0

            common = {
                "origin": "MANUAL",
                "environment": "DEMO",
                "source": "CTRADER_DEAL_HISTORY",
                "evidence_role": "USER_MANUAL_EXECUTION_OUTCOME",
                "position_id": str(position_id),
                "symbol": symbol,
                "symbol_id": symbol_id,
                "direction": direction,
                "position_entry_price": entry_price,
                "position_opened_at": None if opened_at is None else opened_at.isoformat(),
                "position_initial_volume_lots": initial_volume_lots or None,
                "research_track": XAU_RESEARCH_TRACK if symbol == "XAUUSD" else "MANUAL_TRADE_JOURNAL",
                "candidate_strategy_id": XAU_CANDIDATE_STRATEGY if symbol == "XAUUSD" else None,
                "candidate_strategy_match": "UNASSESSED",
                "scanner_signal_id": None,
                "broker_mutation": False,
            }

            for deal in opening_deals:
                deal_id = int(getattr(deal, "dealId", 0) or 0)
                order_id = int(getattr(deal, "orderId", 0) or 0)
                deal_at = _deal_time(deal)
                deal_side = _deal_side(deal)
                payload = {
                    **common,
                    "deal_id": str(deal_id),
                    "order_id": str(order_id) if order_id > 0 else None,
                    "event_time": None if deal_at is None else deal_at.isoformat(),
                    "execution_price": float(getattr(deal, "executionPrice", 0.0) or 0.0) or None,
                    "deal_side": deal_side,
                    "volume_lots": _volume_lots(deal, symbol_id=symbol_id, session=self.session),
                    "partial_close": False,
                }
                if self._record(
                    event_key=f"MANUAL_DEAL:{deal_id}",
                    position_id=position_id,
                    event_type="DEMO_MANUAL_TRADE_OPENED",
                    code="MANUAL_OPEN",
                    payload=payload,
                ):
                    opening_events += 1
                else:
                    duplicates += 1

            close_count = len(closing_deals)
            position_still_open = position_id in open_ids
            for index, deal in enumerate(closing_deals):
                deal_id = int(getattr(deal, "dealId", 0) or 0)
                order_id = int(getattr(deal, "orderId", 0) or 0)
                partial = position_still_open or index < close_count - 1
                close_order = next(
                    (order for order in orders if int(getattr(order, "orderId", 0) or 0) == order_id),
                    None,
                )
                financials = _close_financials(deal)
                net_pnl = float(financials.get("net_pnl_estimate", 0.0) or 0.0)
                outcome = _manual_close_type(close_order, net_pnl=net_pnl, partial=partial)
                deal_at = _deal_time(deal)
                payload = {
                    **common,
                    **financials,
                    "deal_id": str(deal_id),
                    "order_id": str(order_id) if order_id > 0 else None,
                    "event_time": None if deal_at is None else deal_at.isoformat(),
                    "exit_price": float(getattr(deal, "executionPrice", 0.0) or 0.0) or None,
                    "deal_side": _deal_side(deal),
                    "closing_volume_lots": _volume_lots(deal, symbol_id=symbol_id, session=self.session),
                    "partial_close": partial,
                    "exit_type": outcome,
                    "close_order_type": None if close_order is None else int(getattr(close_order, "orderType", 0) or 0),
                    "is_stop_out": bool(getattr(close_order, "isStopOut", False)) if close_order is not None else False,
                }
                event_type = "DEMO_MANUAL_TRADE_PARTIAL_CLOSE" if partial else "DEMO_MANUAL_TRADE_CLOSED"
                if self._record(
                    event_key=f"MANUAL_DEAL:{deal_id}",
                    position_id=position_id,
                    event_type=event_type,
                    code=outcome,
                    payload=payload,
                ):
                    if partial:
                        partial_events += 1
                    else:
                        closed_events += 1
                else:
                    duplicates += 1

        return ManualTradeJournalReport(
            deals=len(accepted_deals),
            positions=len(grouped),
            manual_positions=manual_positions,
            scanner_positions=scanner_positions,
            opening_events=opening_events,
            partial_close_events=partial_events,
            closed_events=closed_events,
            duplicates=duplicates,
            skipped_order_lookup=skipped_order_lookup,
            unresolved_symbol=unresolved_symbol,
            history_truncated=bool(getattr(deals_res, "hasMore", False)),
        )


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    ctrader = policy.ctrader
    if str(ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_DEMO_MANUAL_JOURNAL_DEMO_ONLY")
    if not bool(ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_DEMO_MANUAL_JOURNAL_REQUIRE_DEMO")

    token_store = CTraderTokenStateStore(_required_env(ctrader["token_state_path_env"]))
    tokens = token_store.load(
        fallback_access=_required_env(ctrader["access_token_env"]),
        fallback_refresh=_required_env(ctrader["refresh_token_env"]),
    )
    pinned_account_id = _optional_env(ctrader["account_id_env"])
    session = CTraderOpenApiSession(
        client_id=_required_env(ctrader["client_id_env"]),
        client_secret=_required_env(ctrader["client_secret_env"]),
        access_token=tokens.access_token,
        refresh_token=None,
        token_update_callback=None,
        account_id=None,
        environment="demo",
        request_timeout_seconds=float(ctrader.get("request_timeout_seconds", 10)),
        allow_token_refresh=False,
    )
    store = SupabaseOperationalStore.from_env()
    symbols = [pair.symbol for pair in cfg.pairs]
    try:
        session.resolve_granted_account(
            trader_login=int(_required_env(ctrader["trader_login_env"])),
            require_demo=True,
            pinned_account_id=(None if pinned_account_id is None else int(pinned_account_id)),
        )
        session.connect()
        session.load_symbols(symbols)
        report = DemoManualTradeJournal(
            history=CTraderHistoryClient(session),
            store=store,
            session=session,
            account_id=str(session.account_id),
        ).run_once()
        healthy = not report.history_truncated and report.skipped_order_lookup == 0
        store.write_heartbeat(
            WORKER_NAME,
            healthy=healthy,
            lag_seconds=0.0,
            details={
                "lookback_days": HISTORY_LOOKBACK.days,
                "deals": report.deals,
                "positions": report.positions,
                "manual_positions": report.manual_positions,
                "scanner_positions": report.scanner_positions,
                "opening_events": report.opening_events,
                "partial_close_events": report.partial_close_events,
                "closed_events": report.closed_events,
                "duplicates": report.duplicates,
                "skipped_order_lookup": report.skipped_order_lookup,
                "unresolved_symbol": report.unresolved_symbol,
                "history_truncated": report.history_truncated,
                "broker_mutation": False,
                "token_refresh": False,
                "xau_research_track": XAU_RESEARCH_TRACK,
            },
        )
        print(
            "CTRADER_DEMO_MANUAL_TRADE_JOURNAL_OK "
            f"lookback_days={HISTORY_LOOKBACK.days} deals={report.deals} positions={report.positions} "
            f"manual_positions={report.manual_positions} scanner_positions={report.scanner_positions} "
            f"opened={report.opening_events} partial={report.partial_close_events} "
            f"closed={report.closed_events} duplicates={report.duplicates} "
            f"order_lookup_skips={report.skipped_order_lookup} unresolved_symbol={report.unresolved_symbol} "
            f"truncated={int(report.history_truncated)} broker_mutations=0 token_refreshes=0"
        )
        return 0 if healthy else 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(run())

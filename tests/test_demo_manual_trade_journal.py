from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.demo_manual_trade_journal import DemoManualTradeJournal

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SCANNER_SIGNAL_ID = "12345678-1234-5678-1234-567812345678"


class Obj:
    def __init__(self, *, present=(), **values):
        self._present = set(present)
        for key, value in values.items():
            setattr(self, key, value)

    def HasField(self, name):
        return name in self._present


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self.limit_value = None

    def select(self, _fields): return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def limit(self, value): self.limit_value = int(value); return self

    def execute(self):
        rows = list(self.client.rows[self.table])
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return FakeResponse(rows)


class FakeClient:
    def __init__(self, *, signals=()):
        self.rows = {"signals": list(signals), "broker_order_events": []}

    def table(self, name):
        return FakeQuery(self, name)


class FakeStore:
    def __init__(self, *, signals=()):
        self.client = FakeClient(signals=signals)

    def record_order_event(self, **kwargs):
        self.client.rows["broker_order_events"].append(dict(kwargs))


class FakeHistory:
    def __init__(self, deals, orders_by_position, open_ids=()):
        self.deals = tuple(deals)
        self.orders_by_position = dict(orders_by_position)
        self.open_ids = set(open_ids)

    def recent_deals(self, **_kwargs):
        return Obj(deal=self.deals, hasMore=False)

    def orders_for_position(self, position_id):
        return Obj(order=tuple(self.orders_by_position.get(position_id, ())))

    def open_position_ids(self):
        return set(self.open_ids)


class FakeSession:
    def __init__(self):
        self.symbol_name_by_id = {7: "XAUUSD", 8: "EURUSD"}
        self.symbol_full_by_id = {
            7: Obj(lotSize=100),
            8: Obj(lotSize=100),
        }


def _close_detail(gross_profit=1400):
    return Obj(moneyDigits=2, grossProfit=gross_profit, swap=0, commission=-10, pnlConversionFee=0)


def test_manual_xau_trade_is_backfilled_with_entry_and_final_exit_and_deduped():
    opening = Obj(
        present=(), dealId=1001, orderId=2001, positionId=3001, symbolId=7,
        dealStatus=2, executionTimestamp=1_789_636_800_000, executionPrice=4276.0,
        tradeSide=1, volume=1, comment="manual",
    )
    closing = Obj(
        present=("closePositionDetail",), dealId=1002, orderId=2002, positionId=3001,
        symbolId=7, dealStatus=2, executionTimestamp=1_789_640_400_000,
        executionPrice=4290.0, tradeSide=2, volume=1,
        closePositionDetail=_close_detail(), comment="",
    )
    orders = {
        3001: (
            Obj(orderId=2001, clientOrderId="", orderType=1, isStopOut=False),
            Obj(orderId=2002, clientOrderId="", orderType=4, isStopOut=False),
        )
    }
    store = FakeStore()
    journal = DemoManualTradeJournal(
        history=FakeHistory((opening, closing), orders),
        store=store,
        session=FakeSession(),
        account_id="999",
    )

    first = journal.run_once(now=datetime(2026, 9, 17, 5, 0, tzinfo=UTC))
    assert first.manual_positions == 1
    assert first.scanner_positions == 0
    assert first.opening_events == 1
    assert first.closed_events == 1
    assert first.duplicates == 0

    events = store.client.rows["broker_order_events"]
    assert len(events) == 2
    opened, closed = events
    assert opened["event_type"] == "DEMO_MANUAL_TRADE_OPENED"
    assert opened["signal_key"] == "MANUAL:CTRADER:3001"
    assert opened["payload"]["symbol"] == "XAUUSD"
    assert opened["payload"]["direction"] == "BUY"
    assert opened["payload"]["position_entry_price"] == 4276.0
    assert opened["payload"]["research_track"] == "TELEGRAM_XAU_RECONSTRUCTION"
    assert opened["payload"]["candidate_strategy_match"] == "UNASSESSED"
    assert closed["event_type"] == "DEMO_MANUAL_TRADE_CLOSED"
    assert closed["code"] == "SERVER_PROTECTION_PROFIT"
    assert closed["payload"]["net_pnl_estimate"] == 13.9
    assert closed["payload"]["exit_price"] == 4290.0
    assert closed["payload"]["broker_mutation"] is False

    second = journal.run_once(now=datetime(2026, 9, 17, 5, 1, tzinfo=UTC))
    assert second.opening_events == 0
    assert second.closed_events == 0
    assert second.duplicates == 2
    assert len(store.client.rows["broker_order_events"]) == 2


def test_scanner_linked_position_is_not_mislabeled_as_manual():
    opening = Obj(
        present=(), dealId=1101, orderId=2101, positionId=3101, symbolId=8,
        dealStatus=2, executionTimestamp=1_789_636_800_000, executionPrice=1.1,
        tradeSide=1, volume=1, comment="",
    )
    orders = {3101: (Obj(orderId=2101, clientOrderId=SCANNER_SIGNAL_ID, orderType=1, isStopOut=False),)}
    store = FakeStore(signals=({"id": SCANNER_SIGNAL_ID},))
    journal = DemoManualTradeJournal(
        history=FakeHistory((opening,), orders, open_ids=(3101,)),
        store=store,
        session=FakeSession(),
        account_id="999",
    )
    report = journal.run_once(now=datetime(2026, 9, 17, 5, 0, tzinfo=UTC))
    assert report.scanner_positions == 1
    assert report.manual_positions == 0
    assert store.client.rows["broker_order_events"] == []


def test_open_position_close_deal_is_journaled_as_partial_close():
    opening = Obj(
        present=(), dealId=1201, orderId=2201, positionId=3201, symbolId=7,
        dealStatus=2, executionTimestamp=1_789_636_800_000, executionPrice=4276.0,
        tradeSide=1, volume=2, comment="manual",
    )
    partial = Obj(
        present=("closePositionDetail",), dealId=1202, orderId=2202, positionId=3201,
        symbolId=7, dealStatus=2, executionTimestamp=1_789_638_000_000,
        executionPrice=4281.0, tradeSide=2, volume=1,
        closePositionDetail=_close_detail(500), comment="",
    )
    orders = {3201: (Obj(orderId=2201, clientOrderId="", orderType=1, isStopOut=False), Obj(orderId=2202, clientOrderId="", orderType=1, isStopOut=False))}
    store = FakeStore()
    journal = DemoManualTradeJournal(
        history=FakeHistory((opening, partial), orders, open_ids=(3201,)),
        store=store,
        session=FakeSession(),
        account_id="999",
    )
    report = journal.run_once(now=datetime(2026, 9, 17, 5, 0, tzinfo=UTC))
    assert report.partial_close_events == 1
    close_event = store.client.rows["broker_order_events"][1]
    assert close_event["event_type"] == "DEMO_MANUAL_TRADE_PARTIAL_CLOSE"
    assert close_event["code"] == "PARTIAL_CLOSE_PROFIT"
    assert close_event["payload"]["partial_close"] is True


def test_position_snapshot_workflow_persists_telemetry_and_runs_manual_backfill():
    text = (ROOT / ".github/workflows/ctrader-demo-position-snapshot.yml").read_text()
    live = (ROOT / "src/fx_scanner/demo_live_position_snapshot.py").read_text()
    assert "python -m fx_scanner.demo_live_position_snapshot" in text
    assert "python -m fx_scanner.demo_manual_trade_journal" in text
    assert "SUPABASE_SECRET_KEY" in text
    assert "store=store" in live
    assert "orders_mutated=0 token_refreshes=0 telemetry_persisted=1" in live

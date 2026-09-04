from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fx_scanner.demo_closed_trade_reconciler import DemoClosedTradeReconciler

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SIGNAL_ID = "123e4567-e89b-12d3-a456-426614174000"


class Obj(SimpleNamespace):
    def HasField(self, field):
        return field in getattr(self, "present", ())


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_args):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        rows = list(self.rows)
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        return FakeResponse(rows)


class FakeClient:
    def __init__(self, signal):
        self.rows = {
            "signals": [signal],
            "broker_order_events": [],
        }

    def table(self, name):
        return FakeQuery(self.rows[name])


class FakeStore:
    def __init__(self, signal):
        self.client = FakeClient(signal)

    def record_order_event(self, **row):
        self.client.rows["broker_order_events"].append(row)


class FakeHistory:
    def __init__(self, deals, orders, open_ids=()):
        self.deals = deals
        self.orders = orders
        self.open_ids = set(open_ids)

    def recent_deals(self, **_kwargs):
        return Obj(deal=self.deals, hasMore=False)

    def orders_for_position(self, _position_id):
        return Obj(order=self.orders)

    def open_position_ids(self):
        return set(self.open_ids)


def _signal():
    return {
        "id": SIGNAL_ID,
        "run_id": "run-1",
        "observed_at": "2026-09-04T05:00:00+00:00",
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "final_score": 80.0,
        "entry_low": 1.10,
        "entry_high": 1.101,
        "sl": 1.095,
        "tp2": 1.11,
        "rr2": 1.5,
    }


def _close_detail(*, gross=100, swap=0, commission=0, fee=0, digits=2):
    return Obj(
        moneyDigits=digits,
        grossProfit=gross,
        swap=swap,
        commission=commission,
        pnlConversionFee=fee,
    )


def test_reconciles_scanner_linked_closed_deal():
    detail = _close_detail(gross=125, commission=-5)
    deal = Obj(
        present=("closePositionDetail",),
        dealId=302,
        orderId=402,
        positionId=501,
        dealStatus=2,
        executionTimestamp=1_788_495_600_000,
        executionPrice=1.11,
        closePositionDetail=detail,
        comment=f"FXIS:{SIGNAL_ID}",
    )
    orders = (
        Obj(orderId=401, clientOrderId=SIGNAL_ID, orderType=1, isStopOut=False),
        Obj(orderId=402, clientOrderId="", orderType=4, isStopOut=False),
    )
    store = FakeStore(_signal())
    reconciler = DemoClosedTradeReconciler(
        history=FakeHistory((deal,), orders), store=store, account_id="999"
    )

    report = reconciler.run_once(now=datetime(2026, 9, 4, 6, 0, tzinfo=UTC))
    assert report.persisted == 1
    event = store.client.rows["broker_order_events"][0]
    assert event["event_type"] == "DEMO_TRADE_CLOSED"
    assert event["code"] == "TP_HIT"


def test_partial_close_remains_separate():
    close_detail = _close_detail(gross=100)
    closing_deal = Obj(
        present=("closePositionDetail",),
        dealId=302,
        orderId=402,
        positionId=501,
        dealStatus=2,
        executionTimestamp=1_788_495_600_000,
        executionPrice=1.105,
        closePositionDetail=close_detail,
        comment=f"FXIS:{SIGNAL_ID}",
    )
    orders = (
        Obj(orderId=401, clientOrderId=SIGNAL_ID, orderType=1, isStopOut=False),
        Obj(orderId=402, clientOrderId="", orderType=1, isStopOut=False),
    )
    store = FakeStore(_signal())
    reconciler = DemoClosedTradeReconciler(
        history=FakeHistory((closing_deal,), orders, open_ids=(501,)),
        store=store,
        account_id="999",
    )

    report = reconciler.run_once(now=datetime(2026, 9, 4, 6, 0, tzinfo=UTC))
    assert report.partial_closes == 1
    assert report.persisted == 1
    event = store.client.rows["broker_order_events"][0]
    assert event["event_type"] == "DEMO_TRADE_PARTIAL_CLOSE"
    assert event["code"] == "PARTIAL_CLOSE_PROFIT"


def test_discovery_pipeline_runs_closed_trade_reconciler_best_effort():
    text = (ROOT / ".github/workflows/ctrader-demo-discovery-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in text
    assert "continue-on-error: true" in text
    assert text.index("demo_technical_producer") < text.index(
        "demo_closed_trade_reconciler"
    )
    fast = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "demo_closed_trade_reconciler" not in fast

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.demo_closed_trade_reconciler import (
    DemoClosedTradeReconciler,
    _classify_exit,
    _signal_id_from_orders_or_deals,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SIGNAL_ID = "12345678-1234-5678-1234-567812345678"


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

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, value):
        self.limit_value = int(value)
        return self

    def execute(self):
        rows = list(self.client.rows[self.table])
        for field, value in self.filters:
            rows = [row for row in rows if row.get(field) == value]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return FakeResponse(rows)


class FakeClient:
    def __init__(self, signal):
        self.rows = {
            "signals": [signal],
            "broker_order_events": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


class FakeStore:
    def __init__(self, signal):
        self.client = FakeClient(signal)

    def record_order_event(self, **kwargs):
        row = dict(kwargs)
        self.client.rows["broker_order_events"].append(row)


class FakeHistory:
    def __init__(self, deals, orders, open_ids=()):
        self.deals = tuple(deals)
        self.orders = tuple(orders)
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
        "run_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "observed_at": "2026-09-04T05:00:00+00:00",
        "symbol": "EURUSD",
        "direction": "LONG",
        "setup_type": "TREND_CONTINUATION",
        "final_score": 70.0,
        "entry_low": 1.1000,
        "entry_high": 1.1002,
        "sl": 1.0950,
        "tp2": 1.1100,
        "rr2": 2.0,
    }


def test_server_protection_exit_is_classified_by_planned_sl_tp_geometry():
    signal = _signal()
    protection = Obj(orderType=4, isStopOut=False)
    assert (
        _classify_exit(
            close_order=protection,
            signal=signal,
            exit_price=1.0948,
            gross_profit=-5.0,
            partial=False,
        )
        == "SL_HIT"
    )
    assert (
        _classify_exit(
            close_order=protection,
            signal=signal,
            exit_price=1.1101,
            gross_profit=8.0,
            partial=False,
        )
        == "TP_HIT"
    )


def test_manual_and_stop_out_outcomes_are_distinct():
    signal = _signal()
    manual = Obj(orderType=1, isStopOut=False)
    stop_out = Obj(orderType=1, isStopOut=True)
    assert _classify_exit(
        close_order=manual,
        signal=signal,
        exit_price=1.103,
        gross_profit=1.25,
        partial=False,
    ) == "MANUAL_CLOSE_PROFIT"
    assert _classify_exit(
        close_order=manual,
        signal=signal,
        exit_price=1.098,
        gross_profit=-1.25,
        partial=False,
    ) == "MANUAL_CLOSE_LOSS"
    assert _classify_exit(
        close_order=stop_out,
        signal=signal,
        exit_price=1.090,
        gross_profit=-10.0,
        partial=False,
    ) == "STOP_OUT"


def test_scanner_signal_id_is_recovered_from_client_order_id_first():
    orders = (Obj(clientOrderId=SIGNAL_ID),)
    deals = (Obj(comment=f"FXIS:{SIGNAL_ID}"),)
    assert _signal_id_from_orders_or_deals(orders, deals) == SIGNAL_ID


def test_closed_deal_is_persisted_once_and_then_deduplicated():
    opening_deal = Obj(
        present=(),
        dealId=101,
        orderId=201,
        positionId=301,
        dealStatus=2,
        executionTimestamp=1_788_495_000_000,
        comment=f"FXIS:{SIGNAL_ID}",
    )
    close_detail = Obj(
        moneyDigits=2,
        grossProfit=-325,
        swap=0,
        commission=0,
        pnlConversionFee=0,
    )
    closing_deal = Obj(
        present=("closePositionDetail",),
        dealId=102,
        orderId=202,
        positionId=301,
        dealStatus=2,
        executionTimestamp=1_788_495_600_000,
        executionPrice=1.0949,
        closePositionDetail=close_detail,
        comment="",
    )
    opening_order = Obj(orderId=201, clientOrderId=SIGNAL_ID, orderType=1, isStopOut=False)
    closing_order = Obj(orderId=202, clientOrderId="", orderType=4, isStopOut=False)
    history = FakeHistory((opening_deal, closing_deal), (opening_order, closing_order))
    store = FakeStore(_signal())
    reconciler = DemoClosedTradeReconciler(
        history=history,
        store=store,
        account_id="999",
    )
    now = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)

    first = reconciler.run_once(now=now)
    assert first.closing_deals == 1
    assert first.matched_scanner_trades == 1
    assert first.persisted == 1
    assert first.duplicates == 0
    event = store.client.rows["broker_order_events"][0]
    assert event["event_type"] == "DEMO_TRADE_CLOSED"
    assert event["code"] == "SL_HIT"
    assert event["broker_order_id"] == "DEAL:102"
    assert event["signal_key"] == SIGNAL_ID
    assert event["payload"]["gross_profit"] == -3.25
    assert event["payload"]["exit_type"] == "SL_HIT"

    second = reconciler.run_once(now=now)
    assert second.persisted == 0
    assert second.duplicates == 1
    assert len(store.client.rows["broker_order_events"]) == 1


def test_open_position_close_deal_is_not_counted_as_completed_trade():
    close_detail = Obj(
        moneyDigits=2,
        grossProfit=100,
        swap=0,
        commission=0,
        pnlConversionFee=0,
    )
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


def test_auto_pipeline_runs_closed_trade_reconciler_best_effort():
    text = (ROOT / ".github/workflows/ctrader-demo-auto-pipeline.yml").read_text()
    assert "python -m fx_scanner.demo_closed_trade_reconciler" in text
    assert "continue-on-error: true" in text
    assert text.index("demo_calibration_autotrade --limit 10") < text.index(
        "demo_closed_trade_reconciler"
    )

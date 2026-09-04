from fx_scanner.demo_broker_pnl import TRAJECTORY_WORKER, _update_sampled_trajectory
from fx_scanner.demo_trajectory_finalizer import finalize_trajectories
from fx_scanner.execution.broker_gateway import BrokerBackend, BrokerPositionSnapshot


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = []
        self.limit_value = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, _key, desc=False):
        return self

    def limit(self, value):
        self.limit_value = int(value)
        return self

    def execute(self):
        rows = list(self.client.rows.get(self.table, []))
        for key, value in self.filters:
            rows = [row for row in rows if row.get(key) == value]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return Response(rows)


class Client:
    def __init__(self):
        self.rows = {"runtime_heartbeats": [], "broker_order_events": []}

    def table(self, name):
        return Query(self, name)


class Store:
    def __init__(self):
        self.client = Client()

    def write_heartbeat(self, worker_name, *, healthy, lag_seconds=None, details=None):
        row = {
            "worker_name": worker_name,
            "healthy": healthy,
            "lag_seconds": lag_seconds,
            "details": details or {},
        }
        self.client.rows["runtime_heartbeats"] = [
            item for item in self.client.rows["runtime_heartbeats"]
            if item.get("worker_name") != worker_name
        ] + [row]

    def record_order_event(self, **kwargs):
        self.client.rows["broker_order_events"].append(dict(kwargs))


def position(profit):
    return BrokerPositionSnapshot(
        backend=BrokerBackend.CTRADER,
        position_id="77",
        symbol="EURUSD",
        side="BUY",
        volume=0.01,
        open_price=1.1000,
        current_price=None,
        stop_loss=1.0950,
        take_profit=1.1100,
        profit=profit,
        swap=0.0,
        magic=None,
        comment="FXIS:12345678-1234-5678-1234-567812345678",
    )


def test_sampled_trajectory_accumulates_adverse_and_favorable_extrema():
    store = Store()
    first = _update_sampled_trajectory(store, (position(-2.0),))
    assert first["77"]["sample_count"] == 1
    assert first["77"]["sampled_mae_pnl"] == -2.0
    assert first["77"]["sampled_mfe_pnl"] == 0.0

    second = _update_sampled_trajectory(store, (position(3.5),))
    assert second["77"]["sample_count"] == 2
    assert second["77"]["sampled_mae_pnl"] == -2.0
    assert second["77"]["sampled_mfe_pnl"] == 3.5
    heartbeat = next(
        row for row in store.client.rows["runtime_heartbeats"]
        if row["worker_name"] == TRAJECTORY_WORKER
    )
    assert heartbeat["details"]["positions"]["77"]["trajectory_scope"] == "SINCE_FIRST_OBSERVED"


def test_closed_trade_finalizes_sampled_trajectory_once_without_fake_r_precision():
    store = Store()
    _update_sampled_trajectory(store, (position(-1.25),))
    _update_sampled_trajectory(store, (position(2.75),))
    store.client.rows["broker_order_events"].append(
        {
            "observed_at": "2026-09-04T13:00:00+00:00",
            "backend": "CTRADER",
            "account_id": "999",
            "signal_key": "12345678-1234-5678-1234-567812345678",
            "broker_order_id": "DEAL:501",
            "event_type": "DEMO_TRADE_CLOSED",
            "code": "TP_HIT",
            "payload": {
                "signal_id": "12345678-1234-5678-1234-567812345678",
                "position_id": "77",
                "closing_deal_id": "501",
                "symbol": "EURUSD",
                "direction": "LONG",
                "setup_type": "TREND_CONTINUATION",
                "entry_mode": "HL_PULLBACK",
                "confirmation": "M5_STRUCTURE_BREAK",
                "exit_type": "TP_HIT",
                "net_pnl_estimate": 4.0,
            },
        }
    )

    first = finalize_trajectories(store, account_id="999")
    assert first.finalized == 1
    event = next(
        row for row in store.client.rows["broker_order_events"]
        if row.get("event_type") == "DEMO_TRADE_TRAJECTORY_FINAL"
    )
    payload = event["payload"]
    assert payload["sample_count"] == 2
    assert payload["sampled_mae_pnl"] == -1.25
    assert payload["sampled_mfe_pnl"] == 2.75
    assert payload["entry_mode"] == "HL_PULLBACK"
    assert payload["mae_r"] is None
    assert payload["mfe_r"] is None
    assert payload["r_normalization"] == "DEFERRED_UNTIL_EXACT_BROKER_RISK_DENOMINATOR"

    second = finalize_trajectories(store, account_id="999")
    assert second.finalized == 0
    assert second.duplicates == 1

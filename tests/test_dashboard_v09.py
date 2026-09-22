from fx_scanner.dashboard import DashboardReadError, SupabaseDashboardReader


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = {}
        self.limit_value = None

    def select(self, *args, **kwargs):
        self.client.calls.append(("select", self.table_name))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = int(value)
        return self

    def eq(self, key, value):
        self.filters[str(key)] = value
        return self

    def execute(self):
        rows = list(self.client.data.get(self.table_name, []))
        for key, value in self.filters.items():
            rows = [row for row in rows if row.get(key) == value]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return Response(rows)


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def table(self, name):
        return Query(self, name)


def test_dashboard_reader_uses_latest_run_for_rankings_and_is_read_only():
    client = FakeClient(
        {
            "scanner_runs": [
                {
                    "id": "run-1",
                    "started_at": "2026-08-30T10:00:00+00:00",
                    "mode": "RESEARCH_ONLY",
                    "status": "DONE",
                }
            ],
            "pair_rankings": [
                {"run_id": "run-1", "symbol": "EURUSD", "rank": 1, "coverage": 1.0},
                {"run_id": "old", "symbol": "GBPUSD", "rank": 1, "coverage": 1.0},
            ],
            "signals": [],
            "runtime_heartbeats": [],
            "currency_macro_state": [],
            "model_performance": [],
        }
    )
    snapshot = SupabaseDashboardReader(client).snapshot()
    assert snapshot.latest_run["id"] == "run-1"
    assert [row["symbol"] for row in snapshot.rankings] == ["EURUSD"]
    assert {call[0] for call in client.calls} == {"select"}


def test_dashboard_macro_returns_newest_row_per_currency():
    client = FakeClient(
        {
            "currency_macro_state": [
                {"currency": "USD", "observed_at": "2026-08-30T10:00:00Z", "macro_score": 20},
                {"currency": "EUR", "observed_at": "2026-08-30T09:00:00Z", "macro_score": 10},
                {"currency": "USD", "observed_at": "2026-08-29T10:00:00Z", "macro_score": -5},
            ]
        }
    )
    rows = SupabaseDashboardReader(client).latest_macro()
    assert [row["currency"] for row in rows] == ["EUR", "USD"]
    assert next(row for row in rows if row["currency"] == "USD")["macro_score"] == 20


class BrokenQuery(Query):
    def execute(self):
        raise RuntimeError("network down")


class BrokenClient(FakeClient):
    def table(self, name):
        return BrokenQuery(self, name)


def test_dashboard_reader_wraps_backend_failure():
    reader = SupabaseDashboardReader(BrokenClient({}))
    try:
        reader.latest_signals()
    except DashboardReadError as exc:
        assert "signals read failed" in str(exc)
    else:
        raise AssertionError("DashboardReadError was not raised")


def test_dashboard_reads_coherent_broker_snapshot_positions():
    client = FakeClient({
        "broker_account_state": [{
            "backend": "MT5", "account_id": "123",
            "snapshot_id": "snap-new",
            "observed_at": "2026-08-30T13:00:00Z",
            "balance": 10000.0, "equity": 10025.0,
            "connection_healthy": True,
        }],
        "broker_position_state": [
            {"backend": "MT5", "account_id": "123", "snapshot_id": "snap-new",
             "position_id": "77", "symbol": "EURUSDc", "side": "BUY", "profit": 25.0},
            {"backend": "MT5", "account_id": "123", "snapshot_id": "snap-old",
             "position_id": "66", "symbol": "GBPUSDc", "side": "SELL", "profit": -3.0},
        ],
    })
    reader = SupabaseDashboardReader(client)
    account = reader.latest_broker_account()
    positions = reader.broker_positions_for_account(account)
    assert account["snapshot_id"] == "snap-new"
    assert [row["position_id"] for row in positions] == ["77"]


def test_dashboard_reads_afic_forecast_prepared_and_execution_events():
    client = FakeClient({
        "broker_order_events": [
            {
                "observed_at": "2026-09-22T02:00:00Z",
                "event_type": "DEMO_XAU_AFIC_FORECAST_STATE",
                "code": "XAU_AFIC_PATH_STATE_V1",
                "payload": {"forecast": {"state": "ZONE_TOUCHED_WAIT_CONFIRM"}},
            },
            {
                "observed_at": "2026-09-22T02:01:00Z",
                "event_type": "DEMO_XAU_AFIC_PREPARED_PLAN",
                "code": "XAU_AFIC_PATH_PREPARED_V1",
                "payload": {"prepared_plan": {"entry": 4350.0, "stop": 4340.0}},
            },
            {
                "observed_at": "2026-09-22T02:02:00Z",
                "event_type": "DEMO_SIGNAL_GEOMETRY",
                "code": "XAU_AFIC_PATH_EXECUTION_V1",
                "payload": {"planned_entry": 4351.0, "planned_sl": 4340.0},
            },
            {
                "observed_at": "2026-09-22T02:03:00Z",
                "event_type": "DEMO_SIGNAL_GEOMETRY",
                "code": "OTHER_STRATEGY",
                "payload": {},
            },
        ]
    })
    reader = SupabaseDashboardReader(client)
    states = reader.latest_afic_forecast_states()
    plans = reader.latest_afic_prepared_plans()
    geometry = reader.latest_afic_execution_geometry()
    assert len(states) == 1
    assert states[0]["payload"]["forecast"]["state"] == "ZONE_TOUCHED_WAIT_CONFIRM"
    assert len(plans) == 1
    assert plans[0]["payload"]["prepared_plan"]["entry"] == 4350.0
    assert len(geometry) == 1
    assert geometry[0]["code"] == "XAU_AFIC_PATH_EXECUTION_V1"


def test_dashboard_filters_recent_xau_execution_events():
    client = FakeClient({
        "broker_order_events": [
            {
                "observed_at": "2026-09-22T03:20:00Z",
                "event_type": "ORDER_ACCEPTED",
                "code": "2",
                "accepted": True,
                "signal_key": "afic-signal",
                "broker_order_id": "123",
                "payload": {"symbol": "XAUUSD", "requested_entry": 4350.0},
            },
            {
                "observed_at": "2026-09-22T03:19:00Z",
                "event_type": "DEMO_SIGNAL_GEOMETRY",
                "code": "XAU_AFIC_PATH_EXECUTION_V1",
                "accepted": True,
                "signal_key": "afic-signal",
                "payload": {"symbol": "XAUUSD"},
            },
            {
                "observed_at": "2026-09-22T03:18:00Z",
                "event_type": "ORDER_ACCEPTED",
                "code": "2",
                "accepted": True,
                "signal_key": "eur-signal",
                "payload": {"symbol": "EURUSD"},
            },
        ]
    })
    rows = SupabaseDashboardReader(client).latest_xau_execution_events()
    assert len(rows) == 2
    assert {row["signal_key"] for row in rows} == {"afic-signal"}


def test_dashboard_reader_has_dedicated_xau_signal_feed():
    client = FakeClient({
        "signals": [
            {"observed_at":"2026-09-22T13:00:00Z","symbol":"EURUSD","state":"WATCH"},
            {"observed_at":"2026-09-22T12:59:00Z","symbol":"XAUUSD","state":"SETUP_FORMING"},
            {"observed_at":"2026-09-22T12:58:00Z","symbol":"GBPUSD","state":"WATCH"},
            {"observed_at":"2026-09-22T12:57:00Z","symbol":"XAUUSD","state":"WATCH"},
        ]
    })
    rows = SupabaseDashboardReader(client).latest_signals_for_symbol("xauusd", limit=20)
    assert [row["symbol"] for row in rows] == ["XAUUSD", "XAUUSD"]


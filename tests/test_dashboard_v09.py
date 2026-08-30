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

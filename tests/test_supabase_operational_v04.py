from datetime import datetime, timezone

import pytest

from fx_scanner.config import load_project_config
from fx_scanner.execution.broker_gateway import (
    BrokerAccountSnapshot,
    BrokerBackend,
    BrokerPositionSnapshot,
)
from fx_scanner.exceptions import ConfigurationError
from fx_scanner.storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)

UTC = timezone.utc


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = {}
        self.operation = "select"
        self.payload = None

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _n):
        return self

    def order(self, _name):
        return self

    def upsert(self, payload, **_kwargs):
        self.operation = "upsert"
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def execute(self):
        if self.operation == "select":
            rows = list(self.client.rows.get(self.table_name, []))
            for key, value in self.filters.items():
                rows = [r for r in rows if r.get(key) == value]
            return Response(rows)
        self.client.writes.append((self.table_name, self.operation, self.payload))
        return Response([self.payload])


class FakeClient:
    def __init__(self):
        self.rows = {
            "execution_control": [{
                "control_key": "primary",
                "execution_mode": "DISABLED",
                "new_orders_enabled": False,
                "emergency_stop": True,
                "close_all_requested": False,
                "version": 1,
                "updated_at": "2026-08-30T01:00:00+00:00",
            }],
            "fx_symbols": [{"symbol": "EURUSD", "active": True}, {"symbol": "USDJPY", "active": True}],
        }
        self.writes = []

    def table(self, name):
        return Query(self, name)


def test_reads_fail_closed_control_state():
    store = SupabaseOperationalStore("https://example.supabase.co", "secret", client=FakeClient())
    state = store.get_execution_control()
    assert state.execution_mode == "DISABLED"
    assert state.emergency_stop is True
    assert state.new_orders_enabled is False
    assert state.updated_at.tzinfo is not None


def test_requires_exactly_one_control_row():
    client = FakeClient()
    client.rows["execution_control"] = []
    store = SupabaseOperationalStore("https://example.supabase.co", "secret", client=client)
    with pytest.raises(OperationalStoreUnavailable, match="exactly one"):
        store.get_execution_control()


def test_lists_active_symbols():
    store = SupabaseOperationalStore("https://example.supabase.co", "secret", client=FakeClient())
    assert store.list_active_symbols() == ("EURUSD", "USDJPY")


def test_writes_heartbeat_and_order_event():
    client = FakeClient()
    store = SupabaseOperationalStore("https://example.supabase.co", "secret", client=client)
    store.write_heartbeat("execution_watch", healthy=True, lag_seconds=0.2, details={"ok": True})
    store.record_order_event(
        backend="CTRADER",
        account_id="123",
        signal_key="SIG-1",
        event_type="PREFLIGHT",
        accepted=True,
    )
    assert client.writes[0][0] == "runtime_heartbeats"
    assert client.writes[0][1] == "upsert"
    assert client.writes[1][0] == "broker_order_events"
    assert client.writes[1][1] == "insert"


def test_from_env_prefers_modern_secret_key(monkeypatch):
    client = FakeClient()
    captured = {}

    def factory(url, key):
        captured["url"] = url
        captured["key"] = key
        return client

    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_modern")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy")
    store = SupabaseOperationalStore.from_env(client_factory=factory)
    assert store.client is client
    assert captured == {"url": "https://project.supabase.co", "key": "sb_secret_modern"}


def test_publishes_positions_before_account_snapshot_pointer():
    client = FakeClient()
    store = SupabaseOperationalStore(
        "https://example.supabase.co", "secret", client=client
    )
    account = BrokerAccountSnapshot(
        backend=BrokerBackend.MT5, account_id="123",
        balance=10000.0, equity=10025.0, margin_free=9000.0,
        trade_allowed=False, currency="USC", floating_profit=25.0,
        margin=1000.0, margin_level=1002.5, leverage=500.0,
        server="HFM-Demo",
    )
    position = BrokerPositionSnapshot(
        backend=BrokerBackend.MT5, position_id="77", symbol="EURUSDc",
        side="BUY", volume=0.10, open_price=1.1000, current_price=1.1010,
        stop_loss=1.0950, take_profit=1.1100, profit=25.0, swap=-1.0,
        magic=26083001, comment="FXIS:test",
    )
    snapshot_id = store.publish_broker_telemetry(
        account, [position], broker_name="HFM_CENT", environment="DEMO"
    )
    assert client.writes[-2][0] == "broker_position_state"
    assert client.writes[-1][0] == "broker_account_state"
    assert client.writes[-2][2][0]["snapshot_id"] == snapshot_id
    assert client.writes[-1][2]["snapshot_id"] == snapshot_id


def test_reference_symbol_bootstrap_upserts_xauusd():
    client = FakeClient()
    store = SupabaseOperationalStore(
        "https://example.supabase.co", "secret", client=client
    )
    cfg = load_project_config()

    store.ensure_reference_symbols(cfg.pairs)

    table, operation, payload = client.writes[-1]
    assert table == "fx_symbols"
    assert operation == "upsert"
    assert len(payload) == 16
    xau = next(row for row in payload if row["symbol"] == "XAUUSD")
    assert xau == {
        "symbol": "XAUUSD",
        "base_currency": "XAU",
        "quote_currency": "USD",
        "pip_size": 0.01,
        "tier": "A",
        "active": True,
    }


def test_execution_ready_storage_floor_defaults_to_90():
    client = FakeClient()
    store = SupabaseOperationalStore(
        "https://example.supabase.co", "secret", client=client
    )

    with pytest.raises(OperationalStoreUnavailable, match="below score 90"):
        store.write_signal_rows([
            {
                "state": "EXECUTION_READY",
                "active_guards": [],
                "final_score": 70.0,
                "data_coverage": 0.80,
            }
        ])

    assert client.writes == []


def test_execution_ready_storage_floor_can_be_70_for_explicit_demo_profile():
    client = FakeClient()
    store = SupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
        execution_ready_score_floor=70.0,
    )

    store.write_signal_rows([
        {
            "state": "EXECUTION_READY",
            "active_guards": [],
            "final_score": 70.0,
            "data_coverage": 0.80,
        }
    ])

    assert client.writes[-1][0] == "signals"
    assert client.writes[-1][1] == "insert"


def test_execution_ready_storage_floor_cannot_be_weakened_below_watch_floor():
    with pytest.raises(ConfigurationError, match="within \\[65,100\\]"):
        SupabaseOperationalStore(
            "https://example.supabase.co",
            "secret",
            client=FakeClient(),
            execution_ready_score_floor=64.0,
        )

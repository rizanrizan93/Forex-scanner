from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from fx_scanner.demo_calibration import DemoSupabaseOperationalStore
from fx_scanner.exceptions import ConfigurationError
from fx_scanner.execution import factory
from fx_scanner.storage.supabase_operational import OperationalStoreUnavailable
from fx_scanner.transient import is_transient_backend_error


class _ReferenceQuery:
    def __init__(self, client):
        self.client = client
        self.payload = None

    def upsert(self, payload, **_kwargs):
        self.payload = payload
        return self

    def execute(self):
        self.client.attempts += 1
        if self.client.attempts <= self.client.failures:
            raise RuntimeError(self.client.error)
        self.client.payload = self.payload
        return SimpleNamespace(data=self.payload)


class _ReferenceClient:
    def __init__(self, *, failures: int, error: str = "504 Gateway Timeout"):
        self.failures = failures
        self.error = error
        self.attempts = 0
        self.payload = None

    def table(self, name):
        assert name == "fx_symbols"
        return _ReferenceQuery(self)


def _pair():
    return SimpleNamespace(
        symbol="EURUSD",
        base="EUR",
        quote="USD",
        pip_size=0.0001,
        tier="A",
    )


class _ScannerRunQuery:
    def __init__(self, client):
        self.client = client
        self.payload = None
        self.run_id = None

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, field, value):
        assert field == "id"
        self.run_id = value
        return self

    def execute(self):
        self.client.attempts += 1
        if self.client.attempts <= self.client.failures:
            raise RuntimeError(self.client.error)
        self.client.payloads.append(dict(self.payload))
        return SimpleNamespace(data=[{"id": self.run_id, **self.payload}])


class _ScannerRunClient:
    def __init__(self, *, failures: int, error: str = "504 Gateway Timeout"):
        self.failures = failures
        self.error = error
        self.attempts = 0
        self.payloads = []

    def table(self, name):
        assert name == "scanner_runs"
        return _ScannerRunQuery(self)


class _TokenStore:
    def __init__(self, *, failures: int, transient: bool = True):
        self.failures = failures
        self.transient = transient
        self.attempts = 0

    def load(self, *, fallback_access: str, fallback_refresh: str):
        self.attempts += 1
        if self.attempts <= self.failures:
            if not self.transient:
                raise ConfigurationError("durable cTrader token state is ambiguous")
            try:
                raise RuntimeError("504 Gateway Timeout")
            except RuntimeError as cause:
                raise ConfigurationError(
                    "durable cTrader token-state read failed"
                ) from cause
        return SimpleNamespace(
            access_token=fallback_access,
            refresh_token=fallback_refresh,
        )


def test_transient_classifier_walks_wrapped_504():
    try:
        raise RuntimeError("504 Gateway Timeout")
    except RuntimeError as cause:
        wrapped = ConfigurationError("durable token read failed")
        wrapped.__cause__ = cause
    assert is_transient_backend_error(wrapped) is True
    assert is_transient_backend_error(ConfigurationError("bad configuration")) is False


def test_demo_reference_bootstrap_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ReferenceClient(failures=2)
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )

    store.ensure_reference_symbols((_pair(),))

    assert client.attempts == 3
    assert client.payload[0]["symbol"] == "EURUSD"


def test_demo_reference_bootstrap_persistent_504_fails_closed(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ReferenceClient(failures=9)
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )

    with pytest.raises(
        OperationalStoreUnavailable,
        match="failed after transient retries",
    ):
        store.ensure_reference_symbols((_pair(),))

    assert client.attempts == 3


def test_demo_reference_bootstrap_nontransient_does_not_retry(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ReferenceClient(failures=9, error="401 unauthorized")
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )

    with pytest.raises(OperationalStoreUnavailable):
        store.ensure_reference_symbols((_pair(),))

    assert client.attempts == 1


def test_demo_finish_scanner_run_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ScannerRunClient(failures=2)
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )
    finished_at = datetime(2026, 9, 14, 13, 36, tzinfo=timezone.utc)

    store.finish_scanner_run("run-1", status="SUCCESS", finished_at=finished_at)

    assert client.attempts == 3
    assert len(client.payloads) == 1
    assert client.payloads[0] == {
        "status": "SUCCESS",
        "finished_at": finished_at.isoformat(),
    }


def test_demo_finish_scanner_run_persistent_504_fails_closed(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ScannerRunClient(failures=9)
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )

    with pytest.raises(
        OperationalStoreUnavailable,
        match="scanner_runs finish failed after transient retries",
    ):
        store.finish_scanner_run("run-1", status="SUCCESS")

    assert client.attempts == 3


def test_demo_finish_scanner_run_nontransient_does_not_retry(monkeypatch):
    monkeypatch.setattr("fx_scanner.demo_calibration.time.sleep", lambda _seconds: None)
    client = _ScannerRunClient(failures=9, error="401 unauthorized")
    store = DemoSupabaseOperationalStore(
        "https://example.supabase.co",
        "secret",
        client=client,
    )

    with pytest.raises(OperationalStoreUnavailable):
        store.finish_scanner_run("run-1", status="SUCCESS")

    assert client.attempts == 1


def test_token_load_retries_wrapped_transient_504(monkeypatch):
    monkeypatch.setattr(factory.time, "sleep", lambda _seconds: None)
    store = _TokenStore(failures=2)

    tokens = factory._load_ctrader_tokens(
        store,
        fallback_access="fallback-a",
        fallback_refresh="fallback-r",
    )

    assert store.attempts == 3
    assert tokens.access_token == "fallback-a"
    assert tokens.refresh_token == "fallback-r"


def test_token_load_persistent_504_fails_closed(monkeypatch):
    monkeypatch.setattr(factory.time, "sleep", lambda _seconds: None)
    store = _TokenStore(failures=9)

    with pytest.raises(ConfigurationError, match="after transient retries"):
        factory._load_ctrader_tokens(
            store,
            fallback_access="fallback-a",
            fallback_refresh="fallback-r",
        )

    assert store.attempts == 3


def test_token_load_permanent_state_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(factory.time, "sleep", lambda _seconds: None)
    store = _TokenStore(failures=9, transient=False)

    with pytest.raises(ConfigurationError, match="ambiguous"):
        factory._load_ctrader_tokens(
            store,
            fallback_access="fallback-a",
            fallback_refresh="fallback-r",
        )

    assert store.attempts == 1

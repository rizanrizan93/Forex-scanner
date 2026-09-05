from __future__ import annotations

import json

import pytest

from fx_scanner.exceptions import ConfigurationError
from fx_scanner.execution.ctrader_tokens import CTraderTokenStateStore


class _Response:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, rows: dict[str, dict], name: str):
        self.rows = rows
        self.name = name
        self._mode = None
        self._payload = None
        self._worker = None

    def select(self, _fields: str):
        self._mode = "select"
        return self

    def eq(self, key: str, value):
        assert key == "worker_name"
        self._worker = str(value)
        return self

    def limit(self, _value: int):
        return self

    def upsert(self, payload: dict, on_conflict: str):
        assert on_conflict == "worker_name"
        self._mode = "upsert"
        self._payload = dict(payload)
        return self

    def execute(self):
        assert self.name == "runtime_heartbeats"
        if self._mode == "select":
            row = self.rows.get(str(self._worker))
            return _Response([] if row is None else [dict(row)])
        if self._mode == "upsert":
            worker = str(self._payload["worker_name"])
            self.rows[worker] = dict(self._payload)
            return _Response([dict(self._payload)])
        raise AssertionError("unsupported fake table operation")


class _Client:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def table(self, name: str):
        return _Table(self.rows, name)


def _store(tmp_path, monkeypatch, client: _Client, *, secret: str = "client-secret-A"):
    monkeypatch.setenv("CTRADER_TOKEN_STATE_DURABLE", "1")
    monkeypatch.setenv("CTRADER_CLIENT_SECRET", secret)
    store = CTraderTokenStateStore(tmp_path / "tokens.json")
    store._client = client
    return store


def test_durable_token_round_trip_is_encrypted(tmp_path, monkeypatch):
    client = _Client()
    store = _store(tmp_path, monkeypatch, client)
    store.save("ACCESS-VERY-SECRET", "REFRESH-VERY-SECRET")

    row = client.rows["ctrader_token_state_v1"]
    serialized = json.dumps(row)
    assert "ACCESS-VERY-SECRET" not in serialized
    assert "REFRESH-VERY-SECRET" not in serialized
    assert row["details"]["algorithm"] == "AES-256-GCM"

    fresh = _store(tmp_path, monkeypatch, client)
    loaded = fresh.load(fallback_access="STALE-A", fallback_refresh="STALE-R")
    assert loaded.access_token == "ACCESS-VERY-SECRET"
    assert loaded.refresh_token == "REFRESH-VERY-SECRET"


def test_durable_state_precedes_stale_local_and_fallback(tmp_path, monkeypatch):
    client = _Client()
    store = _store(tmp_path, monkeypatch, client)
    store.save("DURABLE-A", "DURABLE-R")
    (tmp_path / "tokens.json").write_text(
        json.dumps({"access_token": "LOCAL-A", "refresh_token": "LOCAL-R"}),
        encoding="utf-8",
    )

    loaded = store.load(fallback_access="FALLBACK-A", fallback_refresh="FALLBACK-R")
    assert (loaded.access_token, loaded.refresh_token) == ("DURABLE-A", "DURABLE-R")


def test_wrong_encryption_key_fails_closed(tmp_path, monkeypatch):
    client = _Client()
    store = _store(tmp_path, monkeypatch, client, secret="secret-one")
    store.save("A", "R")

    wrong = _store(tmp_path, monkeypatch, client, secret="secret-two")
    with pytest.raises(ConfigurationError, match="cannot be decrypted"):
        wrong.load(fallback_access="FALLBACK-A", fallback_refresh="FALLBACK-R")


def test_probe_proves_backend_without_secret_material(tmp_path, monkeypatch):
    client = _Client()
    store = _store(tmp_path, monkeypatch, client)
    store.probe_durable_backend()

    row = client.rows["ctrader_token_state_vault_probe"]
    assert row["healthy"] is True
    assert row["details"]["contains_secret"] is False
    assert "ciphertext" not in json.dumps(row).lower()

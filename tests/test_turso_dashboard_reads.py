from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import pytest

from fx_scanner.storage.turso_client import Query, Result
from fx_scanner.storage.turso_dashboard_reads import DashboardReadClient


class Local:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path("turso/schema.sql").read_text())
        self.requests = 0
        self.statements = 0
        self.db.execute("INSERT INTO execution_control(control_key) VALUES ('primary')")
        self.db.execute("UPDATE execution_control SET updated_at='2026-10-09T13:00:00+00:00'")

    def table(self, name):
        return Query(self, name)

    def batch(self, statements, **kwargs):
        self.requests += 1
        self.statements += len(statements)
        out = []
        for sql, args in statements:
            cursor = self.db.execute(sql, args)
            out.append(Result([dict(row) for row in cursor.fetchall()]))
        return out

    def usage_snapshot(self):
        return {"requests": self.requests, "statements": self.statements}


def test_batched_publisher_has_identical_payload_and_fewer_round_trips(monkeypatch):
    from fx_scanner import xau_dashboard_bridge_v254 as bridge
    from fx_scanner.storage import backend, turso_dashboard_reads
    monkeypatch.setenv("FX_DATABASE_BACKEND", "turso")
    monkeypatch.setenv("SUPABASE_URL", "https://naxvdtvlfatljzzwhrmo.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")
    now = datetime(2026, 10, 9, 13, tzinfo=UTC)
    databases = []
    def client(*args):
        c = Local()
        for worker in (*bridge.HOT_HEARTBEATS, "ctrader_demo_xau_sd_liquidity_v342",
                       "ctrader_demo_xau_friend_entry_v343"):
            c.db.execute("INSERT INTO runtime_heartbeats(worker_name,observed_at,healthy,details) VALUES (?,?,1,?)",
                         (worker, now.isoformat(), json.dumps({"evaluation": {"state": "WAIT"}})))
        databases.append(c)
        return c
    monkeypatch.setattr(backend, "create_backend_client", client)
    optimized = bridge.build_snapshot(now=now)
    monkeypatch.setattr(turso_dashboard_reads, "prepare_dashboard_reads", lambda c, *a, **k: c)
    baseline = bridge.build_snapshot(now=now)
    assert optimized["backend"] == baseline["backend"]
    assert databases[0].requests <= 8
    assert databases[0].requests * 5 < databases[1].requests
    assert optimized["source"]["database_usage_cycle"]["dashboard_cached_reads"] > 30
    assert optimized["backend"]["heartbeats"][0]["observed_at"] == now.isoformat()


def test_read_cache_is_cycle_scoped_and_rejects_mutations():
    client = Local()
    cached = DashboardReadClient(client)
    query = cached.table("runtime_heartbeats").select("*").eq("worker_name", "test")
    cached.prefetch(query.build())
    query.execute()
    assert client.requests == 1
    client.db.execute("INSERT INTO runtime_heartbeats(worker_name,observed_at,healthy) VALUES ('test','2026-10-09T13:00:00+00:00',1)")
    assert not query.execute().data
    next_cycle = DashboardReadClient(client)
    assert next_cycle.table("runtime_heartbeats").select("*").eq("worker_name", "test").execute().data
    with pytest.raises(ValueError, match="read-only"):
        cached.table("runtime_heartbeats").update({"healthy": False}).eq("worker_name", "test").execute()


def test_failed_prefetch_falls_back_to_real_read():
    client = Local()
    cached = DashboardReadClient(client)
    query = cached.table("runtime_heartbeats").select("*").eq("worker_name", "test")
    original = client.batch
    def fail(*a, **k):
        raise OSError("network")
    client.batch = fail
    cached.prefetch(query.build())
    assert not cached.cache
    client.batch = original
    assert query.execute().data == []
    assert client.requests == 1

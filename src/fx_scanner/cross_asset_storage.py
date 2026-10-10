"""Optional bounded Turso persistence; never writes from a dashboard request."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

SCHEMA_SQL = (
    "CREATE TABLE IF NOT EXISTS cross_asset_state (target_symbol TEXT PRIMARY KEY, timestamp TEXT NOT NULL, model_version TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS lead_lag_calibration (model_version TEXT NOT NULL, target_symbol TEXT NOT NULL, leader_symbol TEXT NOT NULL, session TEXT NOT NULL, regime TEXT NOT NULL, trained_until TEXT NOT NULL, expires_at TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)), payload TEXT NOT NULL, PRIMARY KEY(model_version,target_symbol,leader_symbol,session,regime))",
    "CREATE TABLE IF NOT EXISTS cross_asset_history (target_symbol TEXT NOT NULL, timestamp TEXT NOT NULL, model_version TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(target_symbol,timestamp))",
    "CREATE INDEX IF NOT EXISTS cross_asset_history_ttl ON cross_asset_history(timestamp)",
)


class CrossAssetWriter:
    """One transaction per >=60s; history at most 5m, 7-day bounded retention.

    Explicit migration, never schema creation per tick. Failure returns health
    instead of propagating into the scanner. No silent backend fallback.
    """

    def __init__(self, client, clock=time.monotonic):
        self.client, self.clock = client, clock
        self.last_write = self.last_history = self.last_prune = float("-inf")
        self.last_success_at = None
        self.last_healthy = True

    def migrate(self):
        self.client.batch([(sql, ()) for sql in SCHEMA_SQL], transaction=True)

    def publish(self, states):
        start = self.clock()
        if start - self.last_write < 60:
            return {
                "healthy": self.last_healthy,
                "state": "CACHED",
                "last_success_at": self.last_success_at,
            }
        statements = []
        for state in states:
            try:
                payload = json.dumps(state, allow_nan=False, separators=(",", ":"))
            except (ValueError, TypeError):
                return {"healthy": False, "state": "INVALID_STATE_SERIALIZATION"}
            if len(payload.encode()) > 16384:
                return {"healthy": False, "state": "PAYLOAD_TOO_LARGE"}
            args = (
                state["target_symbol"],
                state["observed_at"],
                state["model_version"],
                state["state"],
                payload,
            )
            statements.append(
                (
                    "INSERT INTO cross_asset_state VALUES(?,?,?,?,?) ON CONFLICT(target_symbol) DO UPDATE SET timestamp=excluded.timestamp,model_version=excluded.model_version,state=excluded.state,payload=excluded.payload WHERE excluded.timestamp>cross_asset_state.timestamp",
                    args,
                )
            )
            if start - self.last_history >= 300:
                statements.append(
                    (
                        "INSERT INTO cross_asset_history VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                        args,
                    )
                )
        if not statements:
            return {
                "healthy": True,
                "state": "NO_STATES",
                "last_success_at": self.last_success_at,
            }
        if start - self.last_prune >= 3600:
            statements.append(
                (
                    "DELETE FROM cross_asset_history WHERE timestamp < ?",
                    ((datetime.now(UTC) - timedelta(days=7)).isoformat(),),
                )
            )
        try:
            self.client.batch(statements, transaction=True)
            self.last_write = start
            if start - self.last_history >= 300:
                self.last_history = start
            if start - self.last_prune >= 3600:
                self.last_prune = start
            self.last_success_at = datetime.now(UTC).isoformat()
            self.last_healthy = True
            return {
                "healthy": True,
                "state": "PUBLISHED",
                "last_success_at": self.last_success_at,
                "latency_ms": (self.clock() - start) * 1000,
            }
        except Exception as exc:  # noqa: BLE001 -- scanner boundary supports heterogeneous database adapters
            # Backoff also applies to failed writes, avoiding an outage retry storm.
            self.last_write = start
            self.last_healthy = False
            return {
                "healthy": False,
                "state": "DATABASE_DEGRADED",
                "error_type": type(exc).__name__,
                "last_success_at": self.last_success_at,
            }

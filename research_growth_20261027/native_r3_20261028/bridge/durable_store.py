"""Durable storage reused from pinned existing RIZAN bridge: private backend behind WSS, durable checkpoints and leases.

The bridge never holds broker credentials and never submits an order. XAU macro/news
snapshots are read-only. State identity is pinned to the frozen contract and the
current cBot checkpoint schema.
"""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import re
import sqlite3
import ssl
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from websockets.asyncio.server import serve
try:
    from .timestamps import validate_timestamps, utc_text
except ImportError:
    from timestamps import validate_timestamps, utc_text

CONTRACTS = {
    "RZEF245": {
        "hash": "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a",
        "schema": 3,
        "execution_model": "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1",
    },
    "RZXA1": {
        "hash": "7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf",
        "schema": 1,
        "execution_model": None,
    },
    "RZEU4B": {
        "hash": "4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976",
        "schema": 2,
        "execution_model": "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1",
    },
    "RZXRC1": {
        "hash": "44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c",
        "schema": 1,
        "execution_model": "XAU_BATCH_SEND_REF_COOLDOWN_V1",
    },
}


def strict_load(text: str):
    return json.loads(
        text,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")),
    )


class Store:
    def __init__(self, path: str | Path, *, clock=time.time):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError("STATE_PATH_INVALID")
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.clock = clock
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints("
            "key TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS bridge_leases("
            "key TEXT PRIMARY KEY, lease TEXT NOT NULL, expires_at REAL NOT NULL, touched_at REAL NOT NULL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoint_receipts("
            "key TEXT NOT NULL, client_revision INTEGER NOT NULL, base INTEGER NOT NULL,"
            "digest TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(key,client_revision))"
        )
        self.db.commit()

    def acquire(self, key: str, lease: str):
        now = self.clock()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute(
                "SELECT lease,expires_at FROM bridge_leases WHERE key=?", (key,)
            ).fetchone()
            if old and old[1] > now and old[0] != lease:
                raise ValueError("LEASE_BUSY")
            row = self.db.execute(
                "SELECT version,state FROM checkpoints WHERE key=?", (key,)
            ).fetchone()
            state = strict_load(row[1]) if row else None
            if row:
                self._validate_state_identity(key, state.get("Revision") if isinstance(state, dict) else None, state)
            self.db.execute(
                "INSERT INTO bridge_leases VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "lease=excluded.lease,expires_at=excluded.expires_at,touched_at=excluded.touched_at",
                (key, lease, now + 45, now),
            )
        return (row[0], state) if row else (0, None)

    def touch(self, key: str, lease: str):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._touch(key, lease)

    def _touch(self, key: str, lease: str):
        now = self.clock()
        updated = self.db.execute(
            "UPDATE bridge_leases SET expires_at=?,touched_at=? "
            "WHERE key=? AND lease=? AND expires_at>?",
            (now + 45, now, key, lease, now),
        ).rowcount
        if updated != 1:
            raise ValueError("LEASE_EXPIRED")

    @staticmethod
    def _validate_state_identity(key: str, revision: int, state: dict) -> None:
        prefix, number, symbol = key.split(":")
        contract = CONTRACTS[prefix]
        if not isinstance(state, dict):
            raise ValueError("STATE_IDENTITY_INVALID")
        if type(state.get("Schema")) is not int or state.get("Schema") != contract["schema"]:
            raise ValueError("STATE_SCHEMA_INVALID")
        if state.get("ContractHash") != contract["hash"]:
            raise ValueError("STATE_CONTRACT_INVALID")
        if str(state.get("AccountNumber")) != number or state.get("Symbol") != symbol:
            raise ValueError("STATE_ACCOUNT_SYMBOL_INVALID")
        if type(revision) is not int or type(state.get("Revision")) is not int or state.get("Revision") != revision or revision < 0:
            raise ValueError("STATE_REVISION_INVALID")
        expected_model = contract["execution_model"]
        if expected_model is not None:
            if state.get("ExecutionModel") != expected_model:
                raise ValueError("STATE_EXECUTION_MODEL_INVALID")
            pending = state.get("PendingChildren", 0)
            if type(pending) is not int or pending < 0 or pending > 2000:
                raise ValueError("STATE_PENDING_CHILDREN_INVALID")

    def save(self, key: str, lease: str, base: int, revision: int, state: dict) -> int:
        if type(base) is not int or base < 0:
            raise ValueError("BASE_REVISION_INVALID")
        self._validate_state_identity(key, revision, state)
        validate_timestamps(state)
        encoded = json.dumps(state, sort_keys=True, allow_nan=False, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self._touch(key, lease)
            receipt = self.db.execute(
                "SELECT base,digest,version FROM checkpoint_receipts WHERE key=? AND client_revision=?",
                (key, revision),
            ).fetchone()
            if receipt:
                if receipt[:2] != (base, digest):
                    raise ValueError("STATE_REVISION_REUSE_CONFLICT")
                # A lost ACK is safe to retry, including after a process restart.
                return receipt[2]
            row = self.db.execute(
                "SELECT version,state FROM checkpoints WHERE key=?", (key,)
            ).fetchone()
            version = int(row[0]) if row else 0
            if row and revision == strict_load(row[1])["Revision"] and base == version - 1:
                legacy = json.dumps(strict_load(row[1]), sort_keys=True, allow_nan=False,
                                    separators=(",", ":"))
                if legacy == encoded:
                    self.db.execute("INSERT INTO checkpoint_receipts VALUES(?,?,?,?,?)",
                                    (key, revision, base, digest, version))
                    return version
            if base != version:
                raise ValueError("REVISION_CONFLICT")
            if row and revision <= strict_load(row[1])["Revision"]:
                raise ValueError("STATE_REVISION_NOT_INCREASING")
            self.db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET version=excluded.version,state=excluded.state",
                (key, version + 1, encoded),
            )
            self.db.execute(
                "INSERT INTO checkpoint_receipts VALUES(?,?,?,?,?)",
                (key, revision, base, digest, version + 1),
            )
        return version + 1

    def status(self, active_keys: set[str]) -> dict:
        rows = self.db.execute("SELECT key,version FROM checkpoints").fetchall()
        result = {}
        for symbol in ("XAUUSD", "EURUSD"):
            versions = [v for key, v in rows if key.split(":")[-1].upper() == symbol]
            connected = sum(key.split(":")[-1].upper() == symbol for key in active_keys)
            result[symbol] = {
                "connected": connected,
                "checkpoint_count": len(versions),
                "checkpoint_version_max": max(versions, default=0),
                "execution_authority": "NONE",
            }
        return result


def _write_snapshot(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(json.dumps(snapshot, allow_nan=False, separators=(",", ":")))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)



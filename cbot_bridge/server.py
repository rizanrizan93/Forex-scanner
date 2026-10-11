"""RIZAN cBot bridge: WSS :25345, durable SQLite checkpoints, exclusive leases.

The bridge never holds broker credentials and never submits an order. XAU macro/news
snapshots are read-only. State identity is pinned to the frozen contract and the
current cBot checkpoint schema.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import sqlite3
import ssl
import time
from pathlib import Path

from websockets.asyncio.server import serve

try:
    from . import feeds
except ImportError:  # direct script execution on VPS
    import feeds

CONTRACTS = {
    # Current XAU cBot.
    "RZXA1": {
        "hash": "7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf",
        "schema": 1,
        "execution_model": None,
    },
    # Current EUR batch cBot v1.1.0.
    "RZEU4B": {
        "hash": "4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976",
        "schema": 2,
        "execution_model": "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1",
    },
}


def strict_load(text: str):
    return json.loads(
        text,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")),
    )


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints("
            "key TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL)"
        )
        self.leases: dict[str, tuple[str, float]] = {}

    def acquire(self, key: str, lease: str):
        old = self.leases.get(key)
        if old and old[1] > time.monotonic() and old[0] != lease:
            raise ValueError("LEASE_BUSY")
        self.leases[key] = (lease, time.monotonic() + 45)
        row = self.db.execute(
            "SELECT version,state FROM checkpoints WHERE key=?", (key,)
        ).fetchone()
        return (row[0], strict_load(row[1])) if row else (0, None)

    def touch(self, key: str, lease: str):
        old = self.leases.get(key)
        if not old or old[0] != lease or old[1] <= time.monotonic():
            raise ValueError("LEASE_EXPIRED")
        self.leases[key] = (lease, time.monotonic() + 45)

    @staticmethod
    def _validate_state_identity(key: str, revision: int, state: dict) -> None:
        prefix, number, symbol = key.split(":")
        contract = CONTRACTS[prefix]
        if not isinstance(state, dict):
            raise ValueError("STATE_IDENTITY_INVALID")
        if state.get("Schema") != contract["schema"]:
            raise ValueError("STATE_SCHEMA_INVALID")
        if state.get("ContractHash") != contract["hash"]:
            raise ValueError("STATE_CONTRACT_INVALID")
        if str(state.get("AccountNumber")) != number or state.get("Symbol") != symbol:
            raise ValueError("STATE_ACCOUNT_SYMBOL_INVALID")
        if state.get("Revision") != revision or not isinstance(revision, int) or revision < 0:
            raise ValueError("STATE_REVISION_INVALID")
        expected_model = contract["execution_model"]
        if expected_model is not None:
            if state.get("ExecutionModel") != expected_model:
                raise ValueError("STATE_EXECUTION_MODEL_INVALID")
            pending = state.get("PendingChildren", 0)
            if not isinstance(pending, int) or pending < 0 or pending > 2000:
                raise ValueError("STATE_PENDING_CHILDREN_INVALID")

    def save(self, key: str, lease: str, base: int, revision: int, state: dict) -> int:
        self.touch(key, lease)
        self._validate_state_identity(key, revision, state)
        encoded = json.dumps(state, allow_nan=False, separators=(",", ":"))
        with self.db:
            row = self.db.execute(
                "SELECT version,state FROM checkpoints WHERE key=?", (key,)
            ).fetchone()
            version = int(row[0]) if row else 0
            if base != version:
                raise ValueError("REVISION_CONFLICT")
            if row and revision <= strict_load(row[1])["Revision"]:
                raise ValueError("STATE_REVISION_NOT_INCREASING")
            self.db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET version=excluded.version,state=excluded.state",
                (key, version + 1, encoded),
            )
        return version + 1


def _validate_identity(key: str, lease: str, contract_hash: str) -> tuple[str, str, str]:
    parts = key.split(":")
    if (
        len(parts) != 3
        or parts[0] not in CONTRACTS
        or not parts[1].isdigit()
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", parts[2])
        or not re.fullmatch(r"[a-f0-9]{32}", lease)
    ):
        raise ValueError("IDENTITY_INVALID")
    expected = CONTRACTS[parts[0]]["hash"]
    if contract_hash != expected:
        raise ValueError("CONTRACT_INVALID")
    expected_symbol = "XAUUSD" if parts[0] == "RZXA1" else "EURUSD"
    if parts[2].upper() != expected_symbol:
        raise ValueError("SYMBOL_INVALID")
    return parts[0], parts[1], parts[2]


async def main() -> None:
    token = os.environ.get("RIZAN_BRIDGE_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("RIZAN_BRIDGE_TOKEN must be a random secret of at least 32 characters")
    host = os.environ.get("RIZAN_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("RIZAN_BRIDGE_PORT", "25345"))
    if port != 25345:
        raise SystemExit("Current cBot contract requires bridge port 25345")

    cert = os.environ.get("RIZAN_TLS_CERT")
    keyfile = os.environ.get("RIZAN_TLS_KEY")
    tls = None
    if cert and keyfile:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, keyfile)
    elif host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit("Public binding requires RIZAN_TLS_CERT and RIZAN_TLS_KEY")

    store = Store(os.environ.get("RIZAN_STATE_DB", "state/rizan-checkpoints.sqlite"))
    peers: set = set()
    latest = None

    async def publish() -> None:
        nonlocal latest
        while True:
            # feeds.snapshot itself fails closed per component and exposes no secret.
            latest = await asyncio.to_thread(feeds.snapshot)
            wire = json.dumps({"type": "snapshot", "data": latest}, allow_nan=False)
            for ws in tuple(peers):
                try:
                    await ws.send(wire)
                except Exception:
                    peers.discard(ws)
            await asyncio.sleep(60)

    async def handler(ws) -> None:
        identity = None
        try:
            hello = strict_load(await asyncio.wait_for(ws.recv(), 10))
            if hello.get("type") != "hello" or not hmac.compare_digest(
                str(hello.get("token", "")), token
            ):
                raise ValueError("AUTH_FAILED")
            key = str(hello.get("key", ""))
            lease = str(hello.get("lease", ""))
            _validate_identity(key, lease, str(hello.get("contract", "")))
            version, state = store.acquire(key, lease)
            identity = (key, lease)
            await ws.send(json.dumps({"type": "ready", "revision": version, "state": state}))
            peers.add(ws)
            if latest is not None:
                await ws.send(
                    json.dumps({"type": "snapshot", "data": latest}, allow_nan=False)
                )
            async for wire in ws:
                request = strict_load(wire)
                if request.get("type") == "ping":
                    store.touch(key, lease)
                    await ws.send('{"type":"pong"}')
                elif request.get("type") == "save":
                    version = store.save(
                        key,
                        lease,
                        int(request["base_revision"]),
                        int(request["client_revision"]),
                        request["state"],
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "type": "ack",
                                "revision": version,
                                "client_revision": request["client_revision"],
                            }
                        )
                    )
                else:
                    raise ValueError("MESSAGE_INVALID")
        except ValueError as exc:
            try:
                await ws.send(json.dumps({"type": "error", "code": str(exc)}))
            finally:
                await ws.close(code=1008)
        except Exception:
            # Never expose token, raw messages, account state, source bodies, or DB errors.
            await ws.close(code=1011)
        finally:
            peers.discard(ws)
            # Lease deliberately survives disconnect for 45 seconds to prevent racing sessions.
            _ = identity

    async with serve(
        handler,
        host,
        port,
        ssl=tls,
        max_size=2_000_000,
        ping_interval=15,
        ping_timeout=15,
    ):
        await publish()


if __name__ == "__main__":
    asyncio.run(main())

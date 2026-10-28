"""R3-only bridge. No broker credentials, order API or production state access."""
from __future__ import annotations
import asyncio
import contextlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import ssl
import time
from websockets.asyncio.server import serve
from durable_store import Store as DurableStore, strict_load, _write_snapshot
from timestamps import validate_timestamps, utc_text
from datetime import datetime, timezone

PROFILE = "fe015394258bf1407ddb90c7d28f3a4e3a2c821a0f019c3c70d487d161c57cbf"
BTC_CONTRACT = "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND"
CONTRACTS = {
    "R3X_fe015394": ("XAUUSD", "44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c", 1, "XAU_BATCH_SEND_REF_COOLDOWN_V1"),
    "R3E_fe015394": ("EURUSD", "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a", 3, "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1"),
}

def identity(key, contract=None):
    if not isinstance(key, str):
        raise ValueError("IDENTITY_INVALID")
    parts = key.split(":")
    if len(parts) == 4 and parts[0] == "R3BTC" and parts[1] == PROFILE:
        number, symbol = parts[2:]
        expected, schema, model = BTC_CONTRACT, 1, None
        if symbol != "BTCUSD":
            raise ValueError("SYMBOL_INVALID")
    elif len(parts) == 3 and parts[0] in CONTRACTS:
        number, symbol = parts[1:]
        expected_symbol, expected, schema, model = CONTRACTS[parts[0]]
        if symbol != expected_symbol:
            raise ValueError("SYMBOL_INVALID")
    else:
        raise ValueError("IDENTITY_INVALID")
    if not re.fullmatch(r"[1-9][0-9]{0,18}", number) or int(number) > 9223372036854775807:
        raise ValueError("ACCOUNT_INVALID")
    if contract is not None and contract != expected:
        raise ValueError("CONTRACT_INVALID")
    return number, symbol, expected, schema, model

class Store(DurableStore):
    @staticmethod
    def _validate_state_identity(key, revision, state):
        number, symbol, contract, schema, model = identity(key)
        if not isinstance(state, dict):
            raise ValueError("STATE_IDENTITY_INVALID")
        if type(state.get("AccountNumber")) is not int or str(state["AccountNumber"]) != number or state.get("Symbol") != symbol:
            raise ValueError("STATE_ACCOUNT_SYMBOL_INVALID")
        if type(state.get("Schema")) is not int or state["Schema"] != schema or state.get("ContractHash") != contract:
            raise ValueError("STATE_CONTRACT_INVALID")
        if type(revision) is not int or revision < 0 or type(state.get("Revision")) is not int or state["Revision"] != revision:
            raise ValueError("STATE_REVISION_INVALID")
        if model is not None:
            if state.get("ExecutionModel") != model:
                raise ValueError("STATE_EXECUTION_MODEL_INVALID")
            pending = state.get("PendingChildren", 0)
            if type(pending) is not int or not 0 <= pending <= 2000:
                raise ValueError("STATE_PENDING_CHILDREN_INVALID")
        else:
            if state.get("NativeProfileHash") != PROFILE:
                raise ValueError("STATE_PROFILE_INVALID")
            for name in ("BatchSent", "BatchRemaining", "NativePendingSequence"):
                if type(state.get(name)) is not int or not 0 <= state[name] <= 32:
                    raise ValueError("STATE_BATCH_INVALID")
            if state["BatchSent"] + state["BatchRemaining"] > 32:
                raise ValueError("STATE_BATCH_INVALID")
            for name in ("Sending", "Fault", "ExitPending", "BatchActive"):
                if type(state.get(name)) is not bool:
                    raise ValueError("STATE_BOOL_INVALID")
            if state["NativePendingSequence"]:
                if not state["Sending"] or not isinstance(state.get("NativePendingLabel"), str) or not state["NativePendingLabel"].startswith("R3B_fe015394|"):
                    raise ValueError("STATE_PENDING_INVALID")
                for name in ("NativePendingMaxUnits", "NativePendingReference"):
                    value = state.get(name)
                    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                        raise ValueError("STATE_PENDING_INVALID")
        validate_timestamps(state)

class Bridge:
    def __init__(self, store, token, *, allowed_accounts=(), clock=time.time):
        if len(token) < 32:
            raise ValueError("TOKEN_MINIMUM_32_CHARACTERS")
        self.store, self.token, self.clock = store, token, clock
        self.allowed_accounts = set(allowed_accounts)
        if not self.allowed_accounts:
            raise ValueError("R3_ACCOUNT_ALLOWLIST_REQUIRED")
        self.peers = {}
        self.snapshot = None
        self.feed = None

    def macro_wire(self):
        if self.snapshot is None:
            return None
        try:
            value = self.snapshot
            at = datetime.fromisoformat(value["ProducedUtc"].replace("Z", "+00:00")).timestamp()
            if not 0 <= self.clock() - at <= 180:
                return None
            validate_timestamps(value)
            return {"type": "snapshot", "data": value}
        except (KeyError, TypeError, ValueError):
            return None

    def btc_wire(self):
        if self.feed is not None and self.feed.get("through") == int(self.clock()) // 3600 * 3600:
            return self.feed
        return {"type": "feed_unavailable"}

    async def send_data(self, ws, symbol):
        wire = self.btc_wire() if symbol == "BTCUSD" else self.macro_wire() if symbol == "XAUUSD" else None
        if wire is not None:
            await ws.send(json.dumps(wire, allow_nan=False, separators=(",", ":")))

    async def broadcast(self):
        for ws, (key, lease) in tuple(self.peers.items()):
            try:
                await self.send_data(ws, identity(key)[1])
            except Exception:
                await ws.close(code=1011)

    async def handler(self, ws):
        try:
            hello = strict_load(await asyncio.wait_for(ws.recv(), 10))
            if not isinstance(hello, dict) or hello.get("type") != "hello" or not hmac.compare_digest(str(hello.get("token", "")), self.token):
                raise ValueError("AUTH_FAILED")
            key, lease = hello.get("key"), hello.get("lease")
            if not isinstance(hello.get("contract"), str):
                raise ValueError("CONTRACT_INVALID")
            number, symbol, *_ = identity(key, hello["contract"])
            if number not in self.allowed_accounts:
                raise ValueError("ACCOUNT_NOT_ALLOWED")
            path = ws.request.path
            if path not in ({"/r3/btc", "/r3/btc/"} if symbol == "BTCUSD" else {"/r3", "/r3/"}):
                raise ValueError("PATH_INVALID")
            if not isinstance(lease, str) or not re.fullmatch(r"[a-f0-9]{32}", lease):
                raise ValueError("LEASE_INVALID")
            if any(peer_key == key for peer_key, _ in self.peers.values()):
                raise ValueError("LEASE_BUSY")
            version, state = self.store.acquire(key, lease)
            self.peers[ws] = (key, lease)
            await ws.send(json.dumps({"type": "ready", "revision": version, "state": state}, allow_nan=False))
            await self.send_data(ws, symbol)
            async for wire in ws:
                request = strict_load(wire)
                if not isinstance(request, dict):
                    raise ValueError("MESSAGE_INVALID")
                if request.get("type") == "ping":
                    self.store.touch(key, lease)
                    await ws.send('{"type":"pong"}')
                    await self.send_data(ws, symbol)
                elif request.get("type") == "save":
                    version = self.store.save(key, lease, request["base_revision"], request["client_revision"], request["state"])
                    await ws.send(json.dumps({"type": "ack", "revision": version, "client_revision": request["client_revision"]}))
                else:
                    raise ValueError("MESSAGE_INVALID")
        except ValueError as exc:
            # Error codes are fixed validation messages, never state/token payloads.
            with contextlib.suppress(Exception):
                await ws.send(json.dumps({"type": "error", "code": str(exc)}))
            with contextlib.suppress(Exception):
                await ws.close(code=1008)
        except Exception:
            with contextlib.suppress(Exception):
                await ws.close(code=1011)
        finally:
            self.peers.pop(ws, None)

async def main():
    import feeds
    from btc_feed import BtcFeed
    folder = Path(os.environ.get("R3_STATE_DIR", "state-r3"))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = os.environ.get("R3_BRIDGE_TOKEN", "")
    accounts = [v.strip() for v in os.environ.get("R3_ALLOWED_ACCOUNTS", "").split(",") if v.strip()]
    bridge = Bridge(Store(folder / "checkpoints.sqlite"), token, allowed_accounts=accounts)
    feed = BtcFeed(Path(os.environ.get("R3_BTC_SEED", "BTC_SEED_PACKET.json")), folder / "btc-m1.sqlite")
    host = os.environ.get("R3_HOST", "127.0.0.1")
    port = int(os.environ.get("R3_PORT", "25347"))
    tls = None
    cert, key = os.environ.get("R3_TLS_CERT"), os.environ.get("R3_TLS_KEY")
    if cert and key:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, key)
    elif host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Public bind requires valid TLS certificate and key")
    async def macro_loop():
        while True:
            try:
                bridge.snapshot = await asyncio.to_thread(feeds.snapshot)
            except Exception:
                bridge.snapshot = None
            await bridge.broadcast()
            await asyncio.sleep(60)
    async def btc_loop():
        while True:
            try:
                bridge.feed = await asyncio.to_thread(feed.packet)
                status = "ready"
            except Exception as ex:
                bridge.feed = None
                status = "unavailable:" + type(ex).__name__
            _write_snapshot(folder / "health.json", {"profile": "R3_I100_W060", "observed_utc": utc_text(datetime.now(timezone.utc)), "btc": status, "macro_snapshot_present": bridge.snapshot is not None, "connected": len(bridge.peers), "execution_authority": "NONE"})
            await bridge.broadcast()
            await asyncio.sleep(15)
    async with serve(bridge.handler, host, port, ssl=tls, max_size=16000000, ping_interval=15, ping_timeout=15):
        print("R3_BRIDGE_LISTENING host=" + host + " port=" + str(port), flush=True)
        await asyncio.gather(macro_loop(), btc_loop())

if __name__ == "__main__":
    asyncio.run(main())

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

PROFILE = "b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128"
BTC_CONTRACT = "RZ-7D130-BTC8500283-LFOLLOW-WEEKEND"
CONTRACTS = {
    "TPX_b6014ae7": ("XAUUSD", "44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c", 1, "XAU_BATCH_SEND_REF_COOLDOWN_V1"),
    "TPE_b6014ae7": ("EURUSD", "d39e1192b64c3044f3215fa82ceaacdb732b4cf758389ad4f609692e54bdae9a", 3, "EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1"),
}

def identity(key, contract=None):
    if not isinstance(key, str):
        raise ValueError("IDENTITY_INVALID")
    parts = key.split(":")
    if len(parts)==4 and parts[0] in {"TPBOOT","TPPROBE"} and parts[1]==PROFILE:
        number,symbol=parts[2:];expected,schema,model=PROFILE,1,"BOOTSTRAP125_V1" if parts[0]=="TPBOOT" else "PROBE"
        if symbol != ("BOOTSTRAP" if parts[0]=="TPBOOT" else "PROBE"):raise ValueError("SYMBOL_INVALID")
    elif len(parts) == 4 and parts[0] == "TPBTC" and parts[1] == PROFILE:
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
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS bootstrap_phase_monotonic BEFORE UPDATE OF state ON checkpoints WHEN OLD.key LIKE 'TPBOOT:%' AND json_extract(OLD.state,'$.Phase')='GROWTH' AND json_extract(NEW.state,'$.Phase')!='GROWTH' BEGIN SELECT RAISE(ABORT,'BOOTSTRAP_PHASE_ROLLBACK'); END""")
        self.db.commit()

    @staticmethod
    def _validate_state_identity(key, revision, state):
        number, symbol, contract, schema, model = identity(key)
        if not isinstance(state, dict):
            raise ValueError("STATE_IDENTITY_INVALID")
        if symbol in {"BOOTSTRAP","PROBE"}:
            if state.get("Schema")!=1 or str(state.get("AccountNumber"))!=number or state.get("Symbol")!=symbol or state.get("ContractHash")!=PROFILE or type(revision) is not int or revision<0 or state.get("Revision")!=revision:raise ValueError("BOOTSTRAP_IDENTITY_INVALID")
            if symbol=="PROBE":return
            if state.get("Phase") not in {"SEED","GROWTH"}:raise ValueError("BOOTSTRAP_PHASE_INVALID")
            if state.get("Phase")=="GROWTH" and (state.get("GraduationBalance",0)<125 or not state.get("GraduatedUtc") or state.get("OpenLabel") or state.get("Intent") is not None):raise ValueError("BOOTSTRAP_GRADUATION_INVALID")
            if type(state.get("Peak")) not in (int,float) or not math.isfinite(state["Peak"]) or state["Peak"]<=0 or type(state.get("Fault")) is not bool:raise ValueError("BOOTSTRAP_STATE_INVALID")
            validate_timestamps(state)
            return
        if type(state.get("AccountNumber")) is not int or str(state["AccountNumber"]) != number or state.get("Symbol") != symbol:
            raise ValueError("STATE_ACCOUNT_SYMBOL_INVALID")
        if type(state.get("Schema")) is not int or state["Schema"] != schema or state.get("ContractHash") != contract:
            raise ValueError("STATE_CONTRACT_INVALID")
        if symbol == "XAUUSD" and state.get("ProfileHash") != PROFILE:
            raise ValueError("STATE_PROFILE_INVALID")
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
                if not state["Sending"] or not isinstance(state.get("NativePendingLabel"), str) or not state["NativePendingLabel"].startswith("TPB_b6014ae7|"):
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
            raise ValueError("BOOT125_ACCOUNT_ALLOWLIST_REQUIRED")
        self.peers = {}
        self.snapshot = None
        self.feed = None
        self.btc_delivery = {}

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
            marker=(wire["type"],wire.get("through"))
            if symbol=="BTCUSD" and self.btc_delivery.get(ws)==marker:return
            await ws.send(json.dumps(wire, allow_nan=False, separators=(",", ":")))
            if symbol=="BTCUSD":self.btc_delivery[ws]=marker

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
            if symbol!="PROBE" and number not in self.allowed_accounts:
                raise ValueError("ACCOUNT_NOT_ALLOWED")
            path = ws.request.path
            if path not in ({"/bootstrap125/btc", "/bootstrap125/btc/"} if symbol == "BTCUSD" else {"/bootstrap125", "/bootstrap125/"}):
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
            self.btc_delivery.pop(ws,None)

def btc_poll_delay(now, fresh):
    boundary=(int(now)//3600+1)*3600
    if not fresh and now%3600<5:return .25
    return max(.05,min(15.,boundary-now))

async def main():
    import feeds
    from btc_feed import BtcFeed
    folder = Path(os.environ.get("BOOT125_STATE_DIR", "state-bootstrap125"))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = os.environ.get("BOOT125_BRIDGE_TOKEN", "")
    accounts = [v.strip() for v in os.environ.get("BOOT125_ALLOWED_ACCOUNTS", "").split(",") if v.strip()]
    bridge = Bridge(Store(folder / "checkpoints.sqlite"), token, allowed_accounts=accounts)
    feed = BtcFeed(Path(os.environ.get("BOOT125_BTC_SEED", "BTC_SEED_PACKET.json")), folder / "btc-m1.sqlite")
    host = os.environ.get("BOOT125_HOST", "127.0.0.1")
    port = int(os.environ.get("BOOT125_PORT", "25356"))
    tls = None
    cert, key = os.environ.get("BOOT125_TLS_CERT"), os.environ.get("BOOT125_TLS_KEY")
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
                completed_hour = int(feed.clock()) // 3600 * 3600
                if bridge.feed is None or bridge.feed.get("through") != completed_hour:
                    bridge.feed = await asyncio.to_thread(feed.packet)
                status = "ready"
            except Exception as ex:
                bridge.feed = None
                status = "unavailable:" + type(ex).__name__
            _write_snapshot(folder / "health.json", {"profile": "RIZAN_BOOTSTRAP125_V1_FROZEN_20261114", "observed_utc": utc_text(datetime.now(timezone.utc)), "btc": status, "macro_snapshot_present": bridge.snapshot is not None, "connected": len(bridge.peers), "execution_authority": "NONE"})
            await bridge.broadcast()
            now=feed.clock()
            await asyncio.sleep(btc_poll_delay(now,bridge.feed is not None and bridge.feed.get("through")==int(now)//3600*3600))
    async with serve(bridge.handler, host, port, ssl=tls, max_size=16000000, ping_interval=15, ping_timeout=15):
        print("BOOT125_BRIDGE_LISTENING host=" + host + " port=" + str(port), flush=True)
        await asyncio.gather(macro_loop(), btc_loop())

if __name__ == "__main__":
    asyncio.run(main())


"""WSS :25345, durable SQLite checkpoints, exclusive leases and read-only feeds."""
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
import feeds

CONTRACTS = {
    'RZEU4B': '4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976',
    'RZXA1': '7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf',
}

def strict_load(text):
    return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS checkpoints(key TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS leases(key TEXT PRIMARY KEY, lease TEXT NOT NULL, expires REAL NOT NULL)')
        self.db.commit()

    def acquire(self, key, lease):
        with self.db:
            old = self.db.execute('SELECT lease,expires FROM leases WHERE key=?', (key,)).fetchone()
            if old and old[1] > time.time() and old[0] != lease:
                raise ValueError('LEASE_BUSY')
            self.db.execute('INSERT INTO leases VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET lease=excluded.lease,expires=excluded.expires', (key, lease, time.time()+45))
        row = self.db.execute('SELECT version,state FROM checkpoints WHERE key=?', (key,)).fetchone()
        return (row[0], strict_load(row[1])) if row else (0, None)

    def touch(self, key, lease):
        with self.db:
            changed = self.db.execute('UPDATE leases SET expires=? WHERE key=? AND lease=? AND expires>?', (time.time()+45, key, lease, time.time())).rowcount
            if changed != 1:
                raise ValueError('LEASE_EXPIRED')

    def save(self, key, lease, base, revision, state):
        self.touch(key, lease)
        prefix, number, symbol = key.split(':')
        if (not isinstance(state, dict) or state.get('Schema') != (2 if prefix == 'RZEU4B' else 1)
                or (prefix == 'RZEU4B' and state.get('ExecutionModel') != 'EUR_BATCH_1S_FILL_ANCHOR_ZONE_V1') or state.get('ContractHash') != CONTRACTS[prefix]
                or str(state.get('AccountNumber')) != number or state.get('Symbol') != symbol
                or state.get('Revision') != revision or type(base) is not int or base < 0 or type(revision) is not int or revision < 0):
            raise ValueError('STATE_IDENTITY_INVALID')
        encoded = json.dumps(state, allow_nan=False, separators=(',', ':'))
        with self.db:
            row = self.db.execute('SELECT version,state FROM checkpoints WHERE key=?', (key,)).fetchone()
            version = row[0] if row else 0
            if base != version:
                raise ValueError('REVISION_CONFLICT')
            if row and revision <= strict_load(row[1])['Revision']:
                raise ValueError('STATE_REVISION_NOT_INCREASING')
            self.db.execute('INSERT INTO checkpoints VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET version=excluded.version,state=excluded.state',
                            (key, version + 1, encoded))
        return version + 1

async def main():
    token = os.environ.get('RIZAN_BRIDGE_TOKEN', '')
    if len(token) < 32 or token.startswith('REPLACE_WITH_'):
        raise SystemExit('Set RIZAN_BRIDGE_TOKEN to a random secret of at least 32 characters.')
    host = os.environ.get('RIZAN_BRIDGE_HOST', '127.0.0.1')
    cert, keyfile = os.environ.get('RIZAN_TLS_CERT'), os.environ.get('RIZAN_TLS_KEY')
    tls = None
    if cert and keyfile:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, keyfile)
    elif host not in ('127.0.0.1', '::1', 'localhost'):
        raise SystemExit('Public binding requires RIZAN_TLS_CERT and RIZAN_TLS_KEY.')
    store = Store(os.environ.get('RIZAN_STATE_DB', 'rizan-checkpoints.sqlite'))
    peers = set()
    active = {}
    latest = None

    async def publish():
        nonlocal latest
        while True:
            try:
                latest = await asyncio.to_thread(feeds.snapshot)
            except Exception:
                # Do not kill heartbeat/checkpoint service or fabricate healthy data.
                latest = None
                await asyncio.sleep(60)
                continue
            wire = json.dumps({'type': 'snapshot', 'data': latest}, allow_nan=False)
            for ws in tuple(peers):
                try:
                    await asyncio.wait_for(ws.send(wire), 5)
                except Exception:
                    peers.discard(ws)
            await asyncio.sleep(60)

    async def handler(ws):
        identity = None
        try:
            hello = strict_load(await asyncio.wait_for(ws.recv(), 10))
            if hello.get('type') != 'hello' or not hmac.compare_digest(str(hello.get('token', '')), token):
                raise ValueError('AUTH_FAILED')
            key, lease = hello.get('key', ''), hello.get('lease', '')
            parts = key.split(':')
            if len(parts) != 3 or parts[0] not in CONTRACTS or not parts[1].isdigit() or not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', parts[2]) or not re.fullmatch(r'[a-f0-9]{32}', lease):
                raise ValueError('IDENTITY_INVALID')
            if hello.get('contract') != CONTRACTS[parts[0]]:
                raise ValueError('CONTRACT_INVALID')
            if key in active:
                raise ValueError('LEASE_BUSY')
            version, state = store.acquire(key, lease)
            active[key] = ws
            identity = (key, lease)
            await ws.send(json.dumps({'type': 'ready', 'revision': version, 'state': state}))
            peers.add(ws)
            if latest is not None:
                await ws.send(json.dumps({'type': 'snapshot', 'data': latest}, allow_nan=False))
            async for wire in ws:
                request = strict_load(wire)
                if request.get('type') == 'ping':
                    store.touch(key, lease)
                    await ws.send('{"type":"pong"}')
                elif request.get('type') == 'save':
                    version = store.save(key, lease, request['base_revision'], request['client_revision'], request['state'])
                    await ws.send(json.dumps({'type': 'ack', 'revision': version, 'client_revision': request['client_revision']}))
                else:
                    raise ValueError('MESSAGE_INVALID')
        except ValueError as exc:
            await ws.send(json.dumps({'type': 'error', 'code': str(exc)}))
            await ws.close(code=1008)
        except Exception:
            # Never expose token, raw messages, account state or SQLite errors.
            await ws.close(code=1011)
        finally:
            peers.discard(ws)
            if identity is not None and active.get(identity[0]) is ws:
                del active[identity[0]]
            # Lease survives disconnect for 45 seconds; restart must wait for
            # expiry, preventing concurrent sessions from racing a broker order.

    async with serve(handler, host, 25345, ssl=tls, max_size=2_000_000, ping_interval=15, ping_timeout=15):
        await publish()

if __name__ == '__main__':
    asyncio.run(main())

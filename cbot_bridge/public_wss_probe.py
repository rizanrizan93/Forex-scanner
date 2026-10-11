"""Read-only WSS deployment probe; synthetic identities, no saves or broker calls."""
import asyncio
import json
import ssl
import uuid
from pathlib import Path
from websockets.asyncio.client import connect

URL = "wss://rizan-bridge.duckdns.org:25345/"
CONTRACTS = {
    "RZXA1": ("XAUUSD", "7ab0cd24eb2e46480d0ba371ba2cd713c5d6bd30747aee71f91ced5a57fce8bf"),
    "RZEU4B": ("EURUSD", "4b4ef3cbe83c26b0752c11d05c866a7345b5db93b8011af091d9e8ad68d77976"),
}

async def main():
    values = {}
    for line in Path("state/cbot-bridge.env").read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep:
            values[name.strip()] = value.strip().strip("'\"")
    token = values["RIZAN_BRIDGE_TOKEN"]
    assert len(token) >= 32
    for prefix, (symbol, contract) in CONTRACTS.items():
        hello = {"type": "hello", "token": token, "key": prefix + ":1:" + symbol,
                 "lease": uuid.uuid4().hex, "contract": contract}
        async with connect(URL, ssl=ssl.create_default_context(), open_timeout=15) as ws:
            await ws.send(json.dumps(hello))
            ready = json.loads(await asyncio.wait_for(ws.recv(), 10))
            assert ready["type"] == "ready"
            assert ready["revision"] == 0 and ready["state"] is None
            if symbol == "XAUUSD":
                snap = json.loads(await asyncio.wait_for(ws.recv(), 10))
                assert snap["type"] == "snapshot"
            await ws.send('{"type":"ping"}')
            pong = json.loads(await asyncio.wait_for(ws.recv(), 10))
            assert pong["type"] == "pong"
            print(symbol + "_PUBLIC_AUTH_HEARTBEAT_PASS")
        async with connect(URL, ssl=ssl.create_default_context(), open_timeout=15) as ws:
            await ws.send(json.dumps(hello))
            assert json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "ready"
            print(symbol + "_PUBLIC_RECONNECT_PASS")
    print("SYNTHETIC_ONLY_NO_CHECKPOINT_WRITE_NO_BROKER_CALL")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print("PUBLIC_PROBE_FAIL_" + type(exc).__name__)
        raise SystemExit(1)

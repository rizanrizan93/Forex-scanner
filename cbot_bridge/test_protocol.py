"""Synthetic clients against a real local WebSocket server, without broker access."""
import asyncio
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
import server
from selftest import state


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_stream_isolation_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = {"RIZAN_BRIDGE_TOKEN": "test-only-" + "x" * 40,
                        "RIZAN_BRIDGE_HOST": "127.0.0.1", "RIZAN_BRIDGE_PORT": "25346",
                        "RIZAN_STATE_DB": str(Path(folder) / "state.sqlite"),
                        "RIZAN_SNAPSHOT_PATH": str(Path(folder) / "snapshot.json"),
                        "RIZAN_HEALTH_PATH": str(Path(folder) / "health.json")}
            fixture = types.SimpleNamespace(snapshot=lambda: {"SyntheticFixture": True})
            with patch.dict(os.environ, settings, clear=True), patch.dict(sys.modules, {"feeds": fixture}):
                task = asyncio.create_task(server.main())
                try:
                    for attempt in range(30):
                        if task.done():
                            await task
                        try:
                            ws = await connect("ws://127.0.0.1:25346")
                            break
                        except OSError:
                            await asyncio.sleep(0.05)
                    else:
                        self.fail("test server not started")
                    async with ws:
                        await ws.send(json.dumps({"type": "hello", "token": "invalid"}))
                        self.assertEqual(json.loads(await ws.recv()), {"type": "error", "code": "AUTH_FAILED"})
                    for prefix, symbol in (("RZXA1", "XAUUSD"), ("RZEU4B", "EURUSD")):
                        hello = {"type": "hello", "token": settings["RIZAN_BRIDGE_TOKEN"],
                                 "key": f"{prefix}:1:{symbol}", "lease": "a" * 32,
                                 "contract": server.CONTRACTS[prefix]["hash"]}
                        async with connect("ws://127.0.0.1:25346") as ws:
                            await ws.send(json.dumps(hello))
                            self.assertEqual(json.loads(await ws.recv())["type"], "ready")
                            if symbol == "XAUUSD":
                                self.assertEqual(json.loads(await ws.recv())["type"], "snapshot")
                            await ws.send('{"type":"ping"}')
                            pong=json.loads(await ws.recv())
                            self.assertEqual(pong["type"], "pong")
                            server.validate_timestamps(pong)
                            save = {"type": "save", "base_revision": 0, "client_revision": 1,
                                    "state": state(prefix, 1, symbol, 1)}
                            for _ in range(2):
                                await ws.send(json.dumps(save))
                                self.assertEqual(json.loads(await ws.recv())["revision"], 1)
                        async with connect("ws://127.0.0.1:25346") as ws:
                            await ws.send(json.dumps(hello))
                            ready = json.loads(await ws.recv())
                            self.assertEqual(ready["revision"], 1)
                            self.assertEqual(ready["state"], save["state"])
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()

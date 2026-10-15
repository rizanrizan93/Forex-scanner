"""Synthetic clients against a real local WebSocket server, without broker access."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.asyncio.client import connect
import server
from selftest import state


class RC1IdentityTests(unittest.TestCase):
    def test_rc1_binding_and_legacy_checkpoint_isolation(self):
        prefix = "RZXRC1"
        contract = server.CONTRACTS[prefix]["hash"]
        server._validate_identity("RZXRC1:1:XAUUSD", "a" * 32, contract)
        with self.assertRaisesRegex(ValueError, "SYMBOL_INVALID"):
            server._validate_identity("RZXRC1:1:EURUSD", "a" * 32, contract)
        with self.assertRaisesRegex(ValueError, "CONTRACT_INVALID"):
            server._validate_identity("RZXRC1:1:XAUUSD", "a" * 32,
                                      server.CONTRACTS["RZXA1"]["hash"])
        with tempfile.TemporaryDirectory() as folder:
            store = server.Store(Path(folder) / "state.sqlite")
            try:
                key = "RZXRC1:1:XAUUSD"
                store.acquire("RZXA1:1:XAUUSD", "b" * 32)
                old = state("RZXA1", 1, "XAUUSD", 1)
                store.save("RZXA1:1:XAUUSD", "b" * 32, 0, 1, old)
                self.assertEqual(store.acquire(key, "a" * 32), (0, None))
                rc1 = state(prefix, 1, "XAUUSD", 1)
                for field, invalid, code in (
                    ("ContractHash", old["ContractHash"], "STATE_CONTRACT_INVALID"),
                    ("Schema", 2, "STATE_SCHEMA_INVALID"),
                    ("ExecutionModel", "OTHER", "STATE_EXECUTION_MODEL_INVALID"),
                ):
                    with self.assertRaisesRegex(ValueError, code):
                        store.save(key, "a" * 32, 0, 1, {**rc1, field: invalid})
                self.assertEqual(store.save(key, "a" * 32, 0, 1, rc1), 1)
                self.assertEqual(store.acquire("RZXA1:1:XAUUSD", "b" * 32), (1, old))
            finally:
                store.db.close()


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_stream_isolation_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            url = f"ws://127.0.0.1:{port}"
            settings = {"RIZAN_BRIDGE_TOKEN": "test-only-" + "x" * 40,
                        "RIZAN_BRIDGE_HOST": "127.0.0.1", "RIZAN_BRIDGE_PORT": str(port),
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
                            ws = await connect(url)
                            break
                        except OSError:
                            await asyncio.sleep(0.05)
                    else:
                        self.fail("test server not started")
                    async with ws:
                        await ws.send(json.dumps({"type": "hello", "token": "invalid"}))
                        self.assertEqual(json.loads(await ws.recv()), {"type": "error", "code": "AUTH_FAILED"})
                    for prefix, symbol in (("RZXA1", "XAUUSD"), ("RZXRC1", "XAUUSD"),
                                           ("RZEU4B", "EURUSD"), ("RZEF245", "EURUSD")):
                        hello = {"type": "hello", "token": settings["RIZAN_BRIDGE_TOKEN"],
                                 "key": f"{prefix}:1:{symbol}", "lease": "a" * 32,
                                 "contract": server.CONTRACTS[prefix]["hash"]}
                        async with connect(url) as ws:
                            await ws.send(json.dumps(hello))
                            response = json.loads(await ws.recv())
                            self.assertEqual(response["type"], "ready",
                                             f"{prefix}: {response.get('code', 'NO_ERROR_CODE')}")
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
                        async with connect(url) as ws:
                            await ws.send(json.dumps(hello))
                            ready = json.loads(await ws.recv())
                            self.assertEqual(ready["revision"], 1)
                            self.assertEqual(ready["state"], save["state"])
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()

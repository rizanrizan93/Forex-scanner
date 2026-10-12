"""Real local WebSocket session registry + checkpoint recovery soak (no broker)."""
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

class SessionSoak(unittest.IsolatedAsyncioTestCase):
    async def test_100_cycles_duplicate_session_invalid_payload_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            env={"RIZAN_BRIDGE_TOKEN":"test-"+"x"*40,"RIZAN_BRIDGE_PORT":"25347",
                 "RIZAN_STATE_DB":str(Path(folder)/"db.sqlite"),
                 "RIZAN_SNAPSHOT_PATH":str(Path(folder)/"snapshot.json"),
                 "RIZAN_HEALTH_PATH":str(Path(folder)/"health.json")}
            fixture=types.SimpleNamespace(snapshot=lambda:{"ProducedUtc":"2026-10-12T13:30:03.640+00:00"})
            with patch.dict(os.environ,env,clear=True),patch.dict(sys.modules,{"feeds":fixture}):
                task=asyncio.create_task(server.main());url="ws://127.0.0.1:25347"
                try:
                    for _ in range(50):
                        if task.done():await task
                        try:
                            ws=await connect(url);await ws.close();break
                        except OSError:await asyncio.sleep(.02)
                    hello={"type":"hello","key":"RZXA1:1:XAUUSD","lease":"b"*32,
                           "contract":server.CONTRACTS["RZXA1"]["hash"],"token":env["RIZAN_BRIDGE_TOKEN"]}
                    saved=state("RZXA1",1,"XAUUSD",1);saved["LastSignalUtc"]="2026-10-12T13:30:03.640Z"
                    for cycle in range(100):
                        async with connect(url) as ws:
                            await ws.send(json.dumps(hello));ready=json.loads(await ws.recv())
                            self.assertEqual(ready["type"],"ready")
                            self.assertEqual(ready["revision"],0 if cycle==0 else 1)
                            if cycle:self.assertEqual(ready["state"],saved)
                            snap=json.loads(await ws.recv());server.validate_timestamps(snap)
                            async with connect(url) as duplicate:
                                await duplicate.send(json.dumps(hello))
                                self.assertEqual(json.loads(await duplicate.recv()),{"type":"error","code":"LEASE_BUSY"})
                            # Same WAL request always produces version 1, including lost ACK retries.
                            await ws.send(json.dumps({"type":"save","base_revision":0,"client_revision":1,"state":saved}))
                            self.assertEqual(json.loads(await ws.recv())["revision"],1)
                            await ws.send('{"type":"ping","timestamp":"2026-10-12T13:30:03.640+00:00"}')
                            self.assertEqual(json.loads(await ws.recv())["type"],"pong")
                            if cycle%2==0:
                                bad={**saved,"Revision":2,"LastSignalUtc":"2026-10-12T13:31:03.640"}
                                await ws.send(json.dumps({"type":"save","base_revision":1,"client_revision":2,"state":bad}))
                                self.assertEqual(json.loads(await ws.recv()),{"type":"error","code":"TIMESTAMP_OFFSET_REQUIRED"})
                            else:
                                await ws.send('{"type":"signal","side":"BUY"}')
                                self.assertEqual(json.loads(await ws.recv()),{"type":"error","code":"MESSAGE_INVALID"})
                finally:
                    task.cancel();await asyncio.gather(task,return_exceptions=True)

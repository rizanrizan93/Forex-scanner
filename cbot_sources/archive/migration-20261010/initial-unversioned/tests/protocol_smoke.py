"""Real localhost WebSocket protocol, SQLite commit and duplicate lease test."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bridge'))
import server
from websockets.asyncio.client import connect

async def test():
    with tempfile.TemporaryDirectory() as folder:
        os.environ.update(RIZAN_BRIDGE_TOKEN='test-token-only-'+'a'*40, RIZAN_BRIDGE_HOST='127.0.0.1',
                          RIZAN_STATE_DB=str(Path(folder)/'checkpoint.sqlite'))
        server.feeds.snapshot = lambda: {'ForexFactoryOk': False, 'BlsOk': False, 'Errors': ['TEST_FEED']}
        task = asyncio.create_task(server.main())
        ws = None
        for _ in range(40):
            try:
                ws = await connect('ws://127.0.0.1:25345')
                break
            except OSError:
                await asyncio.sleep(.05)
        assert ws is not None
        token, key, contract = os.environ['RIZAN_BRIDGE_TOKEN'], 'RZEU3:1237903:EURUSD', server.CONTRACTS['RZEU3']
        hello = {'type':'hello','token':token,'key':key,'contract':contract,'lease':'a'*32}
        await ws.send(json.dumps(hello))
        ready = json.loads(await ws.recv())
        assert ready == {'type':'ready','revision':0,'state':None}
        await ws.recv()  # snapshot
        state = {'Schema':1,'ContractHash':contract,'AccountNumber':1237903,'Symbol':'EURUSD','Revision':1,'PendingLabel':'order-journal'}
        await ws.send(json.dumps({'type':'save','base_revision':0,'client_revision':1,'state':state}))
        ack = json.loads(await ws.recv())
        assert ack == {'type':'ack','revision':1,'client_revision':1}
        await ws.send('{"type":"ping"}')
        assert json.loads(await ws.recv()) == {'type':'pong'}
        async with connect('ws://127.0.0.1:25345') as duplicate:
            await duplicate.send(json.dumps({**hello,'lease':'b'*32}))
            assert json.loads(await duplicate.recv()) == {'type':'error','code':'LEASE_BUSY'}
        await ws.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        persisted = server.Store(os.environ['RIZAN_STATE_DB'])
        assert persisted.acquire(key, 'c'*32) == (1,state)
        persisted.db.close()
    print('PASS: websocket hello/save/ack/ping, duplicate lease rejection, persisted pending order journal')

asyncio.run(test())

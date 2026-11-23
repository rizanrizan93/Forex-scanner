"""Fault injection against pinned released bridge using scratch SQLite and loopback.
No broker session is created. This cannot prove native cTrader cloud recovery.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

if not os.environ.get('RIZAN_V1_REFERENCE_BRIDGE'):
    raise unittest.SkipTest('Pinned released bridge supplied by dedicated P0 workflow')
sys.path.insert(0,os.environ['RIZAN_V1_REFERENCE_BRIDGE'])
from server import Store,Bridge,PROFILE
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

KEY=f'TPBOOT:{PROFILE}:123456:BOOTSTRAP'
OWNER='a'*32
TOKEN='t'*40

def state(revision=1):
    return dict(Schema=1,ContractHash=PROFILE,AccountNumber=123456,Symbol='BOOTSTRAP',Revision=revision,
                Phase='SEED',Fault=False,Peak=100,GraduationBalance=0,
                GraduatedUtc='0001-01-01T00:00:00Z',Intent=None,OpenLabel='')

def hello(owner=OWNER):
    return json.dumps(dict(type='hello',key=KEY,lease=owner,contract=PROFILE,token=TOKEN))

class LeaseSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'state.sqlite'
        self.clock=[100.];self.store=Store(self.path,clock=lambda:self.clock[0]);self.store.acquire(KEY,OWNER)
        self.store.save(KEY,OWNER,0,1,state())
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def test_no_heartbeat_and_exact_expiry_prevent_state_write(self):
        self.clock[0]=145
        with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.store.touch(KEY,OWNER)
        with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.store.save(KEY,OWNER,1,2,state(2))
        self.assertEqual(self.store.db.execute('SELECT version FROM checkpoints WHERE key=?',(KEY,)).fetchone()[0],1)
    def test_reconnect_same_identity_recovers_checkpoint_without_reset(self):
        self.clock[0]=146
        self.assertEqual(self.store.acquire(KEY,OWNER),(1,state()))
        self.store.touch(KEY,OWNER)
    def test_two_owners_rejected_then_old_owner_fenced_after_takeover(self):
        with self.assertRaisesRegex(ValueError,'LEASE_BUSY'):self.store.acquire(KEY,'b'*32)
        self.clock[0]=146;self.store.acquire(KEY,'b'*32)
        with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.store.save(KEY,OWNER,1,2,state(2))
    def test_restart_preserves_pending_intent_and_receipt(self):
        pending=state(2);pending['Intent']={'id':'fixture-pending'}
        self.store.save(KEY,OWNER,1,2,pending);self.store.db.close()
        self.store=Store(self.path,clock=lambda:self.clock[0])
        self.assertEqual(self.store.acquire(KEY,OWNER),(2,pending))
        self.assertEqual(self.store.save(KEY,OWNER,1,2,pending),2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM checkpoint_receipts WHERE key=?',(KEY,)).fetchone()[0],2)
    def test_wrong_account_identity_cannot_overwrite_checkpoint(self):
        bad=state(2);bad['AccountNumber']=999
        with self.assertRaises(ValueError):self.store.save(KEY,OWNER,1,2,bad)
        self.assertEqual(self.store.db.execute('PRAGMA quick_check').fetchone()[0],'ok')

class TransportSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=[100.]
        self.store=Store(Path(self.tmp.name)/'state.sqlite',clock=lambda:self.clock[0])
        self.bridge=Bridge(self.store,TOKEN,allowed_accounts=['123456'],clock=lambda:self.clock[0])
        self.listener=await serve(self.bridge.handler,'127.0.0.1',0)
        self.url='ws://127.0.0.1:'+str(self.listener.sockets[0].getsockname()[1])+'/bootstrap125/'
    async def asyncTearDown(self):
        self.listener.close();await self.listener.wait_closed();self.store.db.close();self.tmp.cleanup()
    async def open(self,owner=OWNER):
        ws=await connect(self.url);await ws.send(hello(owner));return ws,json.loads(await ws.recv())
    async def test_duplicate_live_websocket_rejected_even_same_owner(self):
        a,ready=await self.open();self.assertEqual(ready['type'],'ready')
        try:
            for owner in (OWNER,'b'*32):
                b,r=await self.open(owner)
                self.assertEqual(r['code'],'LEASE_BUSY');await b.close()
        finally:await a.close()
    async def test_abrupt_disconnect_reconnect_preserves_committed_state(self):
        a,r=await self.open()
        await a.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=state())))
        self.assertEqual(json.loads(await a.recv())['type'],'ack')
        a.transport.abort();await a.wait_closed()
        for _ in range(20):
            if not self.bridge.peers:break
            await asyncio.sleep(.01)
        b,r=await self.open()
        try:
            self.assertEqual(r['state'],state());await b.send('{"type":"ping"}')
            self.assertEqual(json.loads(await b.recv())['type'],'pong')
        finally:await b.close()
    async def test_socket_open_but_expired_heartbeat_rejected(self):
        a,r=await self.open();self.clock[0]=146
        try:
            await a.send('{"type":"ping"}')
            self.assertEqual(json.loads(await a.recv())['code'],'LEASE_EXPIRED')
        finally:await a.close()

if __name__=='__main__':unittest.main()

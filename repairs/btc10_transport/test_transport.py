import asyncio,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path('candidate/bridge').resolve()))
import server
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect

class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=[1000.0]
        self.store=server.Store(Path(self.tmp.name)/'db',clock=lambda:self.now[0])
        self.token='test-only-'+'x'*40;self.account='1237903'
        self.bridge=server.Bridge(self.store,self.token,allowed_accounts=[self.account],clock=lambda:1792108800)
        self.bridge.feed={'type':'feed','contract':server.BTC_CONTRACT,'source':'BITSTAMP_BTCUSD_M1','through':1792108800,'bars':[]}
        self.srv=await serve(self.bridge.handler,'127.0.0.1',0)
        self.port=self.srv.sockets[0].getsockname()[1]
    async def asyncTearDown(self):
        self.srv.close();await self.srv.wait_closed();self.store.db.close();self.tmp.cleanup()
    async def open(self,lease='a'*32):
        w=await connect(f'ws://127.0.0.1:{self.port}/btc10/btc')
        key='TPBTC:'+server.PROFILE+':'+self.account+':BTCUSD'
        await w.send(json.dumps(dict(type='hello',key=key,lease=lease,token=self.token,contract=server.BTC_CONTRACT)))
        return w,json.loads(await w.recv())
    async def test_same_lease_replaces_old_socket_and_remains_unique(self):
        old,r=await self.open();self.assertEqual(r['type'],'ready');await old.recv()
        new,r=await self.open();self.assertEqual(r['type'],'ready');await new.recv()
        await old.wait_closed();self.assertEqual(len(self.bridge.peers),1)
        await new.send('{"type":"ping"}');self.assertEqual(json.loads(await new.recv())['type'],'pong')
        await new.close()
    async def test_other_process_cannot_steal_live_lease(self):
        old,r=await self.open();await old.recv()
        new,r=await self.open('b'*32);self.assertEqual(r['code'],'LEASE_BUSY')
        await old.send('{"type":"ping"}');self.assertEqual(json.loads(await old.recv())['type'],'pong')
        self.assertEqual(len(self.bridge.peers),1);await old.close();await new.close()
    async def test_new_process_can_replace_expired_stale_peer(self):
        old,r=await self.open();await old.recv();self.now[0]+=46
        new,r=await self.open('b'*32);self.assertEqual(r['type'],'ready');await new.recv()
        await old.wait_closed();self.assertEqual(len(self.bridge.peers),1);await new.close()
    async def test_heartbeat_keeps_pong_but_sends_seed_only_once_per_hour(self):
        w,r=await self.open();self.assertEqual(json.loads(await w.recv())['type'],'feed')
        for _ in range(6):
            await w.send('{"type":"ping"}');self.assertEqual(json.loads(await w.recv())['type'],'pong')
        with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(w.recv(),.05)
        await w.close();await asyncio.sleep(.02);self.assertFalse(self.bridge.sent_feed)
    async def test_hour_roll_and_feed_recovery_send_new_full_packet(self):
        class Fake:
            def __init__(self):self.sent=[]
            async def send(self,s):self.sent.append(json.loads(s))
        w=Fake();await self.bridge.send_data(w,'BTCUSD');await self.bridge.send_data(w,'BTCUSD')
        self.assertEqual(len(w.sent),1)
        self.bridge.clock=lambda:1792112400
        await self.bridge.send_data(w,'BTCUSD');self.assertEqual(w.sent[-1]['type'],'feed_unavailable')
        self.bridge.feed=dict(self.bridge.feed,through=1792112400)
        await self.bridge.send_data(w,'BTCUSD');await self.bridge.send_data(w,'BTCUSD')
        self.assertEqual(len(w.sent),3);self.assertEqual(w.sent[-1]['type'],'feed')
    async def test_concurrent_same_lease_reconnect_leaves_single_owner(self):
        old,r=await self.open();await old.recv()
        results=await asyncio.gather(self.open(),self.open())
        await asyncio.sleep(.05)
        self.assertEqual(len(self.bridge.peers),1)
        for w,r in results:self.assertEqual(r['type'],'ready');await w.close()

if __name__=='__main__':unittest.main()

import asyncio,csv,json,tempfile,time,unittest
from pathlib import Path
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from server import Bridge,Feed,Store,CONTRACT,SEED_END
ROOT=Path(__file__).resolve().parents[1]
TOKEN='x'*48;ACCOUNT='1237903';KEY=f'RZBTC7D130:{ACCOUNT}:BTCUSD';LEASE='a'*32

def state(rev=1,**kw):return dict(Schema=1,ContractHash=CONTRACT,AccountNumber=int(ACCOUNT),Symbol='BTCUSD',Revision=rev,ExitPending=True,**kw)
class Unit(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.now=[1000.];self.s=Store(Path(self.tmp.name)/'test.sqlite',clock=lambda:self.now[0])
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def test_durable_lease_cas_reopen(self):
  self.assertEqual(self.s.acquire(KEY,LEASE),(0,None));self.assertEqual(self.s.save(KEY,LEASE,0,1,state()),1)
  self.assertEqual(self.s.save(KEY,LEASE,0,1,state()),1) # lost ACK exact replay
  with self.assertRaisesRegex(ValueError,'REUSE_CONFLICT'):self.s.save(KEY,LEASE,0,1,state(Sending=True))
  with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):self.s.save(KEY,LEASE,0,2,state(2))
  with self.assertRaisesRegex(ValueError,'LEASE_BUSY'):self.s.acquire(KEY,'b'*32)
  self.now[0]+=46
  with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.s.save(KEY,LEASE,1,2,state(2))
  self.assertEqual(self.s.acquire(KEY,'b'*32)[1],state())
  self.s.db.close();self.s=Store(Path(self.tmp.name)/'test.sqlite',clock=lambda:self.now[0]);self.assertTrue(self.s.acquire(KEY,'b'*32)[1]['ExitPending'])
 def test_identity_nan_revision(self):
  self.s.acquire(KEY,LEASE)
  for change in [dict(AccountNumber=7),dict(Symbol='XAUUSD'),dict(ContractHash='other'),dict(Schema=2),dict(Revision=True),dict(Revision=-1),dict(Expiry=float('nan'))]:
   x=state();x.update(change)
   with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):self.s.save(KEY,LEASE,0,x['Revision'],x)
 def test_seed_and_contiguous_extension(self):
  f=Feed(ROOT/'bootstrap/BITSTAMP_H1_SEED.csv');self.assertEqual(len(json.loads(f.wire(SEED_END))['bars']),68280)
  with self.assertRaisesRegex(ValueError,'NOT_CURRENT'):f.wire(SEED_END+3600)
  def row(t):return dict(timestamp=str(t),open='80000',high='80001',low='79999',close='80000')
  with self.assertRaisesRegex(ValueError,'M1_GAP'):f.ingest([row(SEED_END+60)],SEED_END+120)
  f.ingest([row(SEED_END+i*60) for i in range(60)],SEED_END+3600)
  self.assertEqual(f.bars[-1][-1],60);self.assertEqual(json.loads(f.wire(SEED_END+3600))['through'],SEED_END+3600)
  self.assertIn('1792112400',f.wire(SEED_END+3600))
  with self.assertRaisesRegex(ValueError,'M1_INVALID'):f.ingest([dict(row(SEED_END+3600),high='nan')],SEED_END+3660)
  # Current unclosed candle is ignored, including weekends.
  before=f.next_minute;f.ingest([row(before)],before);self.assertEqual(f.next_minute,before)

class Network(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite');self.feed=Feed(ROOT/'bootstrap/BITSTAMP_H1_SEED.csv');self.bridge=Bridge(self.store,self.feed,TOKEN,ACCOUNT,clock=lambda:SEED_END)
  self.server=await serve(self.bridge.handler,'127.0.0.1',0,max_size=32000);self.url='ws://127.0.0.1:'+str(self.server.sockets[0].getsockname()[1])
 async def asyncTearDown(self):self.server.close();await self.server.wait_closed();self.store.db.close();self.tmp.cleanup()
 async def hello(self,ws,**kw):
  msg=dict(type='hello',key=KEY,lease=LEASE,contract=CONTRACT,token=TOKEN);msg.update(kw);await ws.send(json.dumps(msg));return json.loads(await ws.recv())
 async def test_auth_account_and_contract(self):
  for kw,code in [(dict(token='bad'),'AUTH_FAILED'),(dict(key='RZBTC7D130:1:BTCUSD'),'IDENTITY_INVALID'),(dict(contract='bad'),'IDENTITY_INVALID')]:
   async with connect(self.url,max_size=16_000_000) as ws:self.assertEqual((await self.hello(ws,**kw))['code'],code)
 async def test_full_feed_checkpoint_ack_and_duplicate(self):
  async with connect(self.url,max_size=16_000_000) as ws:
   self.assertEqual((await self.hello(ws))['type'],'ready');feed=json.loads(await ws.recv());self.assertEqual(feed['type'],'feed')
   self.assertEqual(len(feed['bars']),68280)
   async with connect(self.url,max_size=16_000_000) as other:self.assertEqual((await self.hello(other))['code'],'LEASE_BUSY')
   await ws.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=state())));self.assertEqual(json.loads(await ws.recv())['client_revision'],1)
   await ws.send('{"type":"ping"}');self.assertEqual(json.loads(await ws.recv())['type'],'pong')
   # No duplicate multi-megabyte feed on heartbeat.
   with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(ws.recv(),.05)
  async with connect(self.url,max_size=16_000_000) as ws:
   recovered=await self.hello(ws);self.assertTrue(recovered['state']['ExitPending']);await ws.recv()
   await ws.send('{"type":"order","symbol":"BTCUSD"}');self.assertEqual(json.loads(await ws.recv())['code'],'MESSAGE_INVALID')
 async def test_stale_feed_rejected(self):
  self.bridge.clock=lambda:SEED_END+3600
  async with connect(self.url,max_size=16_000_000) as ws:
   await self.hello(ws);self.assertEqual(json.loads(await ws.recv())['type'],'feed_unavailable')
if __name__=='__main__':unittest.main(verbosity=2)

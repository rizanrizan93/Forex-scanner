import asyncio, copy, json, sqlite3, tempfile, unittest
from pathlib import Path
from datetime import datetime,timezone
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from server import Store, Bridge, PROFILE, BTC_CONTRACT, btc_poll_delay

TOKEN='t'*40; ACCOUNT='123456'; LEASE='a'*32
KEY=f'TPBOOT:{PROFILE}:{ACCOUNT}:BOOTSTRAP'
def seed(rev=1):
 return dict(Schema=1,ContractHash=PROFILE,AccountNumber=int(ACCOUNT),Symbol='BOOTSTRAP',Revision=rev,Phase='SEED',Fault=False,Peak=100,GraduationBalance=0,GraduatedUtc='0001-01-01T00:00:00Z',Intent=None,OpenLabel='')
def hello(key=KEY,lease=LEASE,token=TOKEN,contract=PROFILE):return dict(type='hello',key=key,lease=lease,token=token,contract=contract)
class Storage(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.clock=[100.];self.path=Path(self.tmp.name)/'s.db';self.s=Store(self.path,clock=lambda:self.clock[0]);self.s.acquire(KEY,LEASE)
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def test_ack_loss_durability_cas(self):
  s=seed();self.assertEqual(self.s.save(KEY,LEASE,0,1,s),1);self.s.db.close();self.s=Store(self.path,clock=lambda:self.clock[0]);self.assertEqual(self.s.acquire(KEY,LEASE),(1,s));self.assertEqual(self.s.save(KEY,LEASE,0,1,s),1)
  with self.assertRaisesRegex(ValueError,'REUSE_CONFLICT'):self.s.save(KEY,LEASE,0,1,dict(s,Peak=101))
  with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):self.s.save(KEY,LEASE,0,2,seed(2))
 def test_growth_never_rolls_back(self):
  g=seed();g.update(Phase='GROWTH',GraduationBalance=125,GraduatedUtc='2026-11-14T12:00:00Z');self.s.save(KEY,LEASE,0,1,g)
  with self.assertRaisesRegex(sqlite3.IntegrityError,'PHASE_ROLLBACK'):self.s.save(KEY,LEASE,1,2,seed(2))
  self.assertEqual(self.s.acquire(KEY,LEASE)[1]['Phase'],'GROWTH')
 def test_identity_timestamp_lease(self):
  for bad in [dict(seed(),AccountNumber=234),dict(seed(),ContractHash='bad'),dict(seed(),GraduatedUtc='2026-11-14')]:
   with self.assertRaises(ValueError):self.s.save(KEY,LEASE,0,1,bad)
  with self.assertRaisesRegex(ValueError,'LEASE_BUSY'):self.s.acquire(KEY,'b'*32)
  self.clock[0]+=46;self.s.acquire(KEY,'b'*32)
  with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.s.save(KEY,LEASE,0,1,seed())
 def test_real_csharp_wire(self):
  fixture=Path(__file__).parents[1]/'tests/bin/Release/net8.0/bootstrap_wire_fixture.json'
  if not fixture.exists():self.skipTest('C# fixture supplied in release pipeline')
  state=json.loads(fixture.read_text());state['AccountNumber']=int(ACCOUNT);self.s.save(KEY,LEASE,0,state['Revision'],state)
 def test_btc_hour_boundary_polling(self):
  self.assertAlmostEqual(btc_poll_delay(3599.5,True),.5);self.assertEqual(btc_poll_delay(3600.2,False),.25);self.assertEqual(btc_poll_delay(3610,False),15)
class Transport(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'s.db');self.b=Bridge(self.s,TOKEN,allowed_accounts=[ACCOUNT]);self.server=await serve(self.b.handler,'127.0.0.1',0);self.url='ws://127.0.0.1:'+str(self.server.sockets[0].getsockname()[1])
 async def asyncTearDown(self):self.server.close();await self.server.wait_closed();self.s.db.close();self.tmp.cleanup()
 async def test_save_reconnect(self):
  async with connect(self.url+'/bootstrap125/') as ws:
   await ws.send(json.dumps(hello()));self.assertEqual(json.loads(await ws.recv())['type'],'ready');await ws.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=seed())));self.assertEqual(json.loads(await ws.recv())['type'],'ack')
  await asyncio.sleep(.01)
  async with connect(self.url+'/bootstrap125/') as ws:
   await ws.send(json.dumps(hello()));r=json.loads(await ws.recv());self.assertEqual(r['state'],seed());await ws.send('{"type":"ping"}');self.assertEqual(json.loads(await ws.recv())['type'],'pong')
 async def test_auth_path_allowlist(self):
  for path,msg,code in [('/bootstrap125/',hello(token='bad'),'AUTH_FAILED'),('/buy050/',hello(),'PATH_INVALID'),('/bootstrap125/',hello(key=f'TPBOOT:{PROFILE}:234567:BOOTSTRAP'),'ACCOUNT_NOT_ALLOWED')]:
   async with connect(self.url+path) as ws:await ws.send(json.dumps(msg));self.assertEqual(json.loads(await ws.recv())['code'],code)
 async def test_feed_delivered_once_per_connection(self):
  self.b.feed=dict(type='feed',through=int(self.b.clock())//3600*3600,bars=[])
  key=f'TPBTC:{PROFILE}:{ACCOUNT}:BTCUSD'
  async with connect(self.url+'/bootstrap125/btc') as ws:
   await ws.send(json.dumps(hello(key=key,contract=BTC_CONTRACT)));await ws.recv();self.assertEqual(json.loads(await ws.recv())['type'],'feed');await ws.send('{"type":"ping"}');self.assertEqual(json.loads(await ws.recv())['type'],'pong')
   with self.assertRaises(asyncio.TimeoutError):await asyncio.wait_for(ws.recv(),.05)
  await asyncio.sleep(.01)
  async with connect(self.url+'/bootstrap125/btc') as ws:
   await ws.send(json.dumps(hello(key=key,contract=BTC_CONTRACT)));await ws.recv();self.assertEqual(json.loads(await ws.recv())['type'],'feed')
if __name__=='__main__':unittest.main(verbosity=2)

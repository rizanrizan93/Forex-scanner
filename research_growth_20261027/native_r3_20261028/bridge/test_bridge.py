import asyncio,copy,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
import server
from btc_feed import BtcFeed,SEED_END

TOKEN='test-only-token-not-production-'+'x'*32
ACCOUNT='1237903'
BTC='R3BTC:'+server.PROFILE+':'+ACCOUNT+':BTCUSD'
XAU='R3X_fe015394:'+ACCOUNT+':XAUUSD'
EUR='R3E_fe015394:'+ACCOUNT+':EURUSD'
def state(key,rev=1):
 number,symbol,contract,schema,model=server.identity(key)
 d=dict(Schema=schema,ContractHash=contract,AccountNumber=int(number),Symbol=symbol,Revision=rev)
 if model:d.update(ExecutionModel=model,PendingChildren=0)
 else:d.update(NativeProfileHash=server.PROFILE,BatchSent=0,BatchRemaining=0,NativePendingSequence=0,Sending=False,Fault=False,ExitPending=False,BatchActive=False,NativePendingLabel='',NativePendingMaxUnits=0,NativePendingReference=0)
 return d
class DurableTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.now=[1000.0];self.store=server.Store(Path(self.tmp.name)/'db',clock=lambda:self.now[0])
 def tearDown(self):self.store.db.close();self.tmp.cleanup()
 def test_all_three_contracts_roundtrip_and_restart(self):
  for key in [XAU,EUR,BTC]:
   self.assertEqual(self.store.acquire(key,'a'*32),(0,None));s=state(key)
   self.assertEqual(self.store.save(key,'a'*32,0,1,s),1)
  self.store.db.close();self.store=server.Store(Path(self.tmp.name)/'db',clock=lambda:self.now[0])
  for key in [XAU,EUR,BTC]:self.assertEqual(self.store.acquire(key,'a'*32),(1,state(key)))
 def test_lost_ack_idempotent_receipt(self):
  self.store.acquire(BTC,'a'*32);s=state(BTC);self.assertEqual(self.store.save(BTC,'a'*32,0,1,s),1);self.assertEqual(self.store.save(BTC,'a'*32,0,1,s),1)
  s['Fault']=True
  with self.assertRaisesRegex(ValueError,'REUSE_CONFLICT'):self.store.save(BTC,'a'*32,0,1,s)
 def test_lease_expiry_old_writer_blocked(self):
  self.store.acquire(BTC,'a'*32)
  with self.assertRaisesRegex(ValueError,'LEASE_BUSY'):self.store.acquire(BTC,'b'*32)
  self.now[0]+=46;self.store.acquire(BTC,'b'*32)
  with self.assertRaisesRegex(ValueError,'LEASE_EXPIRED'):self.store.save(BTC,'a'*32,0,1,state(BTC))
  self.assertEqual(self.store.save(BTC,'b'*32,0,1,state(BTC)),1)
 def test_legacy_live_namespaces_rejected(self):
  for key in ['RZXRC1:1237903:XAUUSD','RZEF245:1237903:EURUSD','RZBTC7D130:1237903:BTCUSD']:
   with self.assertRaises(ValueError):server.identity(key)
 def test_wrong_account_symbol_contract_profile_rejected(self):
  for field,value in [('AccountNumber',1),('Symbol','XAUUSD'),('ContractHash','wrong'),('NativeProfileHash','wrong'),('Schema',2),('Revision',True),('BatchSent',33),('BatchRemaining',33),('Sending',1)]:
   s=state(BTC);s[field]=value
   with self.subTest(field=field),self.assertRaises(ValueError):self.store._validate_state_identity(BTC,1,s)
 def test_pending_intent_preserved_and_validated(self):
  self.store.acquire(BTC,'a'*32);s=state(BTC);s.update(BatchSent=1,BatchRemaining=31,NativePendingSequence=2,Sending=True,NativePendingLabel='R3B_fe015394|123|B2',NativePendingMaxUnits=90,NativePendingReference=100000000)
  self.store.save(BTC,'a'*32,0,1,s);self.assertEqual(self.store.acquire(BTC,'a'*32)[1],s)
  s['BatchRemaining']=32
  with self.assertRaises(ValueError):self.store._validate_state_identity(BTC,1,s)
 def test_cas_wrong_revision_and_nan(self):
  self.store.acquire(BTC,'a'*32)
  with self.assertRaisesRegex(ValueError,'REVISION_CONFLICT'):self.store.save(BTC,'a'*32,5,1,state(BTC))
  with self.assertRaises(ValueError):server.strict_load('{"value":NaN}')
 def test_timestamps_offset_required(self):
  self.store.acquire(XAU,'a'*32);s=state(XAU);s['EpochUtc']='2026-10-28T12:00:00'
  with self.assertRaises(ValueError):self.store.save(XAU,'a'*32,0,1,s)

class WireTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=server.Store(Path(self.tmp.name)/'db');self.bridge=server.Bridge(self.store,TOKEN,allowed_accounts=[ACCOUNT],clock=lambda:SEED_END)
  self.bridge.feed={'type':'feed','through':SEED_END,'contract':server.BTC_CONTRACT,'source':'BITSTAMP_BTCUSD_M1','bars':[]}
  self.srv=await serve(self.bridge.handler,'127.0.0.1',0,max_size=16000000);self.port=self.srv.sockets[0].getsockname()[1]
 async def asyncTearDown(self):
  self.srv.close();await self.srv.wait_closed();self.store.db.close();self.tmp.cleanup()
 async def open(self,key=BTC,token=TOKEN,lease='a'*32,path=None,contract=None):
  path=path or ('/r3/btc' if key==BTC else '/r3/')
  ws=await connect(f'ws://127.0.0.1:{self.port}'+path,max_size=16000000)
  await ws.send(json.dumps(dict(type='hello',key=key,lease=lease,contract=contract or server.identity(key)[2],token=token)))
  return ws,json.loads(await ws.recv())
 async def test_ready_feed_save_ack_and_ping(self):
  ws,r=await self.open();self.assertEqual(r,dict(type='ready',revision=0,state=None));self.assertEqual(json.loads(await ws.recv())['type'],'feed')
  await ws.send(json.dumps(dict(type='save',base_revision=0,client_revision=1,state=state(BTC))));self.assertEqual(json.loads(await ws.recv()),dict(type='ack',revision=1,client_revision=1))
  await ws.send('{"type":"ping"}');self.assertEqual(json.loads(await ws.recv())['type'],'pong');self.assertEqual(json.loads(await ws.recv())['type'],'feed');await ws.close()
 async def test_parallel_xau_eur_btc_separate_keys(self):
  opened=[]
  for key in [XAU,EUR,BTC]:
   ws,r=await self.open(key);opened.append(ws);self.assertEqual(r['type'],'ready')
  self.assertEqual(len(self.bridge.peers),3)
  for ws in opened:await ws.close()
 async def test_wrong_token_rejected(self):
  ws,r=await self.open(token='wrong');self.assertEqual(r['code'],'AUTH_FAILED');await ws.close()
 async def test_second_instance_rejected(self):
  ws,r=await self.open();await ws.recv();other,r=await self.open(lease='b'*32);self.assertEqual(r['code'],'LEASE_BUSY');await other.close();await ws.close()
 async def test_wrong_path_and_contract_rejected(self):
  for kwargs,code in [({'path':'/'},'PATH_INVALID'),({'contract':'wrong'},'CONTRACT_INVALID')]:
   ws,r=await self.open(**kwargs);self.assertEqual(r['code'],code);await ws.close()
 async def test_allowlist_enforced(self):
  key=BTC.replace(ACCOUNT,'999')
  ws,r=await self.open(key,path='/r3/btc');self.assertEqual(r['code'],'ACCOUNT_NOT_ALLOWED');await ws.close()
 async def test_stale_btc_not_published(self):
  self.bridge.feed['through']-=3600;ws,r=await self.open();self.assertEqual(json.loads(await ws.recv())['type'],'feed_unavailable');await ws.close()
 async def test_no_btc_packet_not_published(self):
  self.bridge.feed=None;ws,r=await self.open();self.assertEqual(json.loads(await ws.recv())['type'],'feed_unavailable');await ws.close()

class FeedTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.seed=Path(__file__).with_name('BTC_SEED_PACKET.json')
 def setUp(self):self.tmp=tempfile.TemporaryDirectory()
 def tearDown(self):self.tmp.cleanup()
 def feed(self,now,fetch):return BtcFeed(self.seed,Path(self.tmp.name)/'m1.db',clock=lambda:now,fetch=fetch)
 def test_real_seed_and_no_fetch_when_current(self):
  def fail(*args):raise AssertionError('unexpected network')
  packet=self.feed(SEED_END,fail).packet();self.assertEqual(len(packet['bars']),68280);self.assertEqual(packet['through'],SEED_END)
 def test_m1_extension_and_cache_restart(self):
  calls=[]
  def fetch(start,end):
   calls.append((start,end));return [dict(timestamp=str(at),open='100',high='102',low='99',close='101') for at in range(start,end,60)]
  f=self.feed(SEED_END+3600,fetch);p=f.packet();self.assertEqual(p['bars'][-1],[SEED_END,100,102,99,101,60]);self.assertEqual(len(calls),1)
  def fail(*args):raise AssertionError('cache was not durable')
  g=self.feed(SEED_END+3600,fail);self.assertEqual(g.packet(),p)
 def test_missing_minute_never_synthesized(self):
  def fetch(start,end):return [dict(timestamp=str(at),open='100',high='102',low='99',close='101') for at in range(start+60,end,60)]
  with self.assertRaisesRegex(ValueError,'SOURCE_MINUTE_GAP'):self.feed(SEED_END+3600,fetch).packet()
 def test_invalid_prices_rejected(self):
  for v in ['nan','-1','inf']:
   with self.subTest(value=v),self.assertRaises(ValueError):BtcFeed.minute(dict(timestamp=str(SEED_END),open=v,high='102',low='99',close='101'))
 def test_seed_tampering_rejected(self):
  p=Path(self.tmp.name)/'seed';d=json.loads(self.seed.read_text());d['bars'][0][1]+=1;p.write_text(json.dumps(d))
  with self.assertRaises(ValueError):BtcFeed(p,Path(self.tmp.name)/'db')
 def test_clock_older_than_seed_rejected(self):
  with self.assertRaises(ValueError):self.feed(SEED_END-3600,lambda *a:[]).packet()

if __name__=='__main__':unittest.main(verbosity=2)

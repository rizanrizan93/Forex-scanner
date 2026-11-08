"""Regression: stale original native frames rejected; synthetic profile-corrected frames roundtrip."""
import json,tempfile,unittest
from pathlib import Path
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from server import Bridge,Store,PROFILE
from test_bridge import TOKEN
class ActualNativeFrames(unittest.IsolatedAsyncioTestCase):
 async def test_three_csharp_checkpoints_over_real_websocket(self):
  root=Path(__file__).resolve().parents[1]/'validation/native_fixtures'
  raw=[json.loads((root/(name+'.json')).read_text()) for name in ['XAU','EUR','BTC']]
  # The archived fixtures predate BUY050: never present them as native BUY050 output.
  self.assertNotEqual(raw[0]['ProfileHash'],PROFILE)
  self.assertNotEqual(raw[2]['NativeProfileHash'],PROFILE)
  fixtures=json.loads(json.dumps(raw))
  fixtures[0]['ProfileHash']=PROFILE
  fixtures[2]['NativeProfileHash']=PROFILE
  account=str(fixtures[0]['AccountNumber'])
  with tempfile.TemporaryDirectory() as folder:
   store=Store(Path(folder)/'db');bridge=Bridge(store,TOKEN,allowed_accounts=[account])
   try:
    async with serve(bridge.handler,'127.0.0.1',0) as srv:
     port=srv.sockets[0].getsockname()[1]
     for state in fixtures:
      btc=state['Symbol']=='BTCUSD';prefix='TPBTC:'+PROFILE if btc else 'TPX_13bfa137' if state['Symbol']=='XAUUSD' else 'TPE_13bfa137'
      key=prefix+':'+str(state['AccountNumber'])+':'+state['Symbol'];path='/buy050/btc' if btc else '/buy050/'
      async with connect(f'ws://127.0.0.1:{port}'+path) as ws:
       await ws.send(json.dumps(dict(type='hello',token=TOKEN,key=key,lease='e'*32,contract=state['ContractHash'])))
       self.assertEqual(json.loads(await ws.recv())['type'],'ready')
       if btc:self.assertEqual(json.loads(await ws.recv())['type'],'feed_unavailable')
       await ws.send(json.dumps(dict(type='save',base_revision=0,client_revision=state['Revision'],state=state)))
       ack=json.loads(await ws.recv());self.assertEqual(ack,dict(type='ack',revision=1,client_revision=state['Revision']))
       self.assertEqual(store.acquire(key,'e'*32),(1,state))
     # Confirm old original account-matched XAU/BTC frames cannot enter the BUY050 DB.
     for stale in (raw[0],raw[2]):
      prefix='TPX_13bfa137' if stale['Symbol']=='XAUUSD' else 'TPBTC:'+PROFILE
      key=prefix+':'+account+':'+stale['Symbol']
      with self.assertRaisesRegex(ValueError,'STATE_PROFILE_INVALID'):
       store._validate_state_identity(key,stale['Revision'],stale)
   finally:store.db.close()

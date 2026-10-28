"""Authenticated, order-free bridge preflight. Token only from environment."""
import asyncio,json,os,time,uuid
from datetime import datetime
from urllib.parse import urlsplit
from websockets.asyncio.client import connect
from server import PROFILE,BTC_CONTRACT,CONTRACTS

def macro_ok(value):
 try:
  ts=lambda key:datetime.fromisoformat(value[key].replace('Z','+00:00')).timestamp()
  now=time.time()
  return value['ForexFactoryOk'] is True and value['BlsOk'] is True and value['Dgs10'] is not None and value['Dfii10'] is not None and 0<=now-ts('ProducedUtc')<=180 and ts('CoverageFromUtc')<=now-1800 and ts('CoverageToUtc')>=now+495*60
 except (KeyError,TypeError,ValueError):return False
async def main():
 base=os.environ.get('R3_PUBLIC_URL','').rstrip('/')
 uri=urlsplit(base)
 if uri.scheme!='wss' or uri.port!=25345 or uri.path!='/r3' or uri.query or uri.fragment or uri.username:raise SystemExit('R3_PUBLIC_URL must be wss://your-host:25345/r3')
 token=os.environ.get('R3_BRIDGE_TOKEN','');account=os.environ.get('R3_PROBE_ACCOUNT','')
 if len(token)<32 or not account.isdigit():raise SystemExit('Set R3_BRIDGE_TOKEN and R3_PROBE_ACCOUNT privately')
 result={}
 for symbol in ['EURUSD','XAUUSD','BTCUSD']:
  if symbol=='BTCUSD':key='R3BTC:'+PROFILE+':'+account+':BTCUSD';contract=BTC_CONTRACT;url=base+'/btc'
  else:
   prefix='R3X_fe015394' if symbol=='XAUUSD' else 'R3E_fe015394';key=prefix+':'+account+':'+symbol;contract=CONTRACTS[prefix][1];url=base+'/'
  async with connect(url,max_size=16000000,open_timeout=10) as ws:
   await ws.send(json.dumps(dict(type='hello',key=key,lease=uuid.uuid4().hex,contract=contract,token=token)))
   ready=json.loads(await asyncio.wait_for(ws.recv(),10))
   if ready.get('type')!='ready':raise SystemExit(symbol+': handshake failed '+str(ready.get('code','unknown')))
   await ws.send('{"type":"ping"}');pong=False;data=symbol=='EURUSD';deadline=time.monotonic()+8
   while time.monotonic()<deadline and not(pong and data):
    try:r=json.loads(await asyncio.wait_for(ws.recv(),max(.1,deadline-time.monotonic())))
    except asyncio.TimeoutError:break
    if r.get('type')=='pong':pong=True
    elif r.get('type')=='snapshot':data=macro_ok(r.get('data',{}))
    elif r.get('type')=='feed':data=r.get('contract')==BTC_CONTRACT and r.get('source')=='BITSTAMP_BTCUSD_M1' and r.get('through')==int(time.time())//3600*3600 and len(r.get('bars',[]))>=68280
    elif r.get('type')=='error':raise SystemExit(symbol+': '+str(r.get('code')))
   result[symbol]={'handshake':True,'heartbeat':pong,'data_ready':data,'orders':0}
 print(json.dumps(result,indent=2))
 if not all(v['heartbeat'] and v['data_ready'] for v in result.values()):raise SystemExit('Feed not ready; keep cBot order switch OFF')
 print('PASS. Wait60 seconds for diagnostic leases to expire before starting the cBot.')
if __name__=='__main__':asyncio.run(main())

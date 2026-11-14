"""Authenticated TLS smoke test. No broker API; checkpoint writes only in PROBE namespace."""
import asyncio,json,os,uuid,time
from datetime import datetime,timezone
from websockets.asyncio.client import connect
PROFILE='b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128'
async def main():
 token=os.environ['BOOT125_BRIDGE_TOKEN'];url=os.environ.get('BOOT125_PUBLIC_URL','wss://rizan-bridge.duckdns.org:25345/bootstrap125/');lease=uuid.uuid4().hex;key=f'TPPROBE:{PROFILE}:9000000000000000001:PROBE'
 async def open_probe():
  ws=await connect(url,open_timeout=15,close_timeout=5,max_size=16000000);await ws.send(json.dumps(dict(type='hello',token=token,key=key,lease=lease,contract=PROFILE)));r=json.loads(await asyncio.wait_for(ws.recv(),15));assert r['type']=='ready', 'PROBE_AUTH_FAILED';return ws,r
 ws,r=await open_probe();base=r['revision'];revision=(r['state'] or {}).get('Revision',0)+1;state=dict(Schema=1,AccountNumber=9000000000000000001,Symbol='PROBE',ContractHash=PROFILE,Revision=revision,ObservedUtc=datetime.now(timezone.utc).isoformat())
 await ws.send(json.dumps(dict(type='save',base_revision=base,client_revision=revision,state=state)));ack=json.loads(await asyncio.wait_for(ws.recv(),15));assert ack['type']=='ack' and ack['revision']==base+1,'PROBE_ACK_FAILED';await ws.close();await asyncio.sleep(.15)
 ws,r=await open_probe();assert r['state']==state and r['revision']==base+1,'PROBE_RECONNECT_STATE_FAILED';await ws.send('{"type":"ping"}');assert json.loads(await asyncio.wait_for(ws.recv(),15))['type']=='pong','PROBE_HEARTBEAT_FAILED';await ws.close()
 # Read-only BTC feed handshake on a fresh namespace; no checkpoint or broker action.
 account=os.environ['BOOT125_ALLOWED_ACCOUNTS'].split(',')[0];btc=False;macro=False
 for symbol,prefix,contract,path in [('BTCUSD','TPBTC:'+PROFILE,'RZ-7D130-BTC8500283-LFOLLOW-WEEKEND',url.rstrip('/')+'/btc'),('XAUUSD','TPX_b6014ae7','44db60b75e3eb19c0fb94f10baca96f35ab4686086a70eea53f626533ca9923c',url)]:
  async with connect(path,open_timeout=15,close_timeout=5,max_size=16000000) as w:
   await w.send(json.dumps(dict(type='hello',token=token,key=f'{prefix}:{account}:{symbol}',lease=uuid.uuid4().hex,contract=contract)));ready=json.loads(await asyncio.wait_for(w.recv(),15));assert ready['type']=='ready','FEED_AUTH_FAILED'
   if symbol=='BTCUSD':
    wire=json.loads(await asyncio.wait_for(w.recv(),20));btc=wire.get('type')=='feed' and wire.get('through')==int(time.time())//3600*3600
   else:
    try:macro=json.loads(await asyncio.wait_for(w.recv(),2)).get('type')=='snapshot'
    except asyncio.TimeoutError:pass
 print(json.dumps(dict(public_tls=True,authenticated=True,durable_ack=True,reconnect_readback=True,heartbeat=True,btc_current_hour=btc,macro_snapshot=macro,broker_orders=0,token_printed=False)))
if __name__=='__main__':asyncio.run(main())

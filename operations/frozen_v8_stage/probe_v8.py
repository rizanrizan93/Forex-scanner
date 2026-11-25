"""Public TLS, actual cTrader-produced wire frames, synthetic account only."""
import asyncio,json,sys,time,uuid
from pathlib import Path
from websockets.asyncio.client import connect
ACCOUNT=9000000000000000002
URL="wss://rizan-bridge.duckdns.org:25345/v8frozen/"
token=next(l.split("=",1)[1] for l in Path(sys.argv[2]).read_text().splitlines() if l.startswith("BOOT125_BRIDGE_TOKEN="))
wires=json.loads(Path(sys.argv[1]).read_text())
roles={}
for w in wires:
 h=w["hello"];s=w["save"];parts=h["key"].split(":");role=parts[-1]
 if role in {"BOOTSTRAP","XAUUSD","EURUSD","BTCUSD"} and role not in roles:roles[role]=(h,s)
assert set(roles)=={"BOOTSTRAP","XAUUSD","EURUSD","BTCUSD"}
async def main():
 seen={};feed={"fresh":False,"macro":False}
 def observe(x):
  if x.get("type")=="feed":
   feed["fresh"]=x.get("through")==int(time.time())//3600*3600 and x.get("source")=="BITSTAMP_BTCUSD_M1" and bool(x.get("bars"))
  if x.get("type")=="snapshot":feed["macro"]=True
 async def until(w,kind,seconds=20):
  end=time.monotonic()+seconds
  while True:
   x=json.loads(await asyncio.wait_for(w.recv(),max(.01,end-time.monotonic())))
   observe(x)
   if x.get("type")=="error":raise RuntimeError("PUBLIC_BRIDGE_REJECTED_"+str(x.get("code")))
   if x.get("type")==kind:return x
 for role,(oh,req) in roles.items():
  h=dict(oh);parts=h["key"].split(":");parts[-2]=str(ACCOUNT);h.update(key=":".join(parts),token=token,lease=uuid.uuid4().hex)
  path=URL+"btc" if role=="BTCUSD" else URL
  state=dict(req["state"]);state["AccountNumber"]=ACCOUNT
  async with connect(path,open_timeout=15,close_timeout=5,max_size=16000000) as w:
   await w.send(json.dumps(h));r=await until(w,"ready")
   assert r["state"] is None and r["revision"]==0
   await w.send(json.dumps(dict(type="save",base_revision=0,client_revision=state["Revision"],state=state)))
   a=await until(w,"ack");assert a["revision"]==1 and a["client_revision"]==state["Revision"]
   await w.send('{"type":"ping"}');await until(w,"pong")
  await asyncio.sleep(.1)
  async with connect(path,open_timeout=15,close_timeout=5,max_size=16000000) as w:
   await w.send(json.dumps(h));r=await until(w,"ready");assert r["state"]==state and r["revision"]==1
   await w.send('{"type":"ping"}');await until(w,"pong")
   if role=="BTCUSD" and not feed["fresh"]:
    end=time.monotonic()+55
    while not feed["fresh"] and time.monotonic()<end:
     await w.send('{"type":"ping"}');await until(w,"pong")
     try:observe(json.loads(await asyncio.wait_for(w.recv(),3)))
     except asyncio.TimeoutError:pass
   seen[role]={"authenticated":True,"checkpoint_ack":True,"reconnect_readback":True}
 # Reject a different synthetic account, without acquiring any LIVE account lease.
 h=dict(roles["BOOTSTRAP"][0]);parts=h["key"].split(":");parts[-2]=str(ACCOUNT+1);h.update(key=":".join(parts),token=token,lease=uuid.uuid4().hex)
 async with connect(URL,open_timeout=15,max_size=16000000) as w:
  await w.send(json.dumps(h));r=json.loads(await asyncio.wait_for(w.recv(),10));assert r.get("code")=="ACCOUNT_NOT_ALLOWED"
 print(json.dumps(dict(public_wss=True,all_four_roles=len(seen)==4,roles=seen,durable_reconnect=True,btc_feed_fresh=feed["fresh"],macro_snapshot_present=feed["macro"],account_allowlist_guard=True,broker_orders=0,token_printed=False)))
if __name__=="__main__":asyncio.run(main())

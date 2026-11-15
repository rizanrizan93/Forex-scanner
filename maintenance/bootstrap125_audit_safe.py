"""Safe bridge audit: leases and checkpoint writes confined to PROBE namespace."""
import asyncio,json,os,shlex,sqlite3,subprocess,time,uuid,sys
sys.path.insert(0,'/opt/rizan-bootstrap125-bridge')
from server import Store
from pathlib import Path
from datetime import datetime,timezone
from websockets.asyncio.client import connect
PROFILE='b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128'
def envread():
 d={}
 for line in Path('/etc/rizan-bootstrap125-bridge.env').read_text().splitlines():
  if '=' in line and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);p=shlex.split(v);d[k.strip()]=p[0] if len(p)==1 else v
 return d
async def main():
 env=envread();state=Path(env['BOOT125_STATE_DIR']);report={'observed_utc':datetime.now(timezone.utc).isoformat(),'broker_orders':0,'trading_state_writes':0,'services':{}}
 for u in ['rizan-bootstrap125-bridge.service','rizan-buy050-bridge.service']:
  r=subprocess.run(['systemctl','show',u,'-p','ActiveState','-p','SubState','-p','NRestarts','-p','MemoryCurrent','-p','ExecMainStartTimestampMonotonic'],capture_output=True,text=True,check=True)
  report['services'][u]=dict(x.split('=',1) for x in r.stdout.splitlines() if '=' in x)
 health=json.loads((state/'health.json').read_text());report['health_before_probe']=health
 report['health_age_seconds']=round(time.time()-datetime.fromisoformat(health['observed_utc'].replace('Z','+00:00')).timestamp(),3)
 report['trading_checkpoints']=[]
 with sqlite3.connect((state/'checkpoints.sqlite').as_uri()+'?mode=ro',uri=True) as db:
  for key,version,s in db.execute("SELECT key,version,state FROM checkpoints WHERE key NOT LIKE 'TPPROBE:%'"):
   value=json.loads(s)
   try:Store._validate_state_identity(key,value.get('Revision'),value);valid=True
   except Exception:valid=False
   report['trading_checkpoints'].append({'symbol':key.split(':')[-1],'account_suffix':str(value.get('AccountNumber',''))[-4:],'version':version,'client_revision':value.get('Revision'),'identity_valid':valid,'phase':value.get('Phase'),'fault':value.get('Fault'),'reason':value.get('Reason',value.get('QuarantineReason','')),'quarantined':value.get('Quarantined'),'intent_present':value.get('Intent') is not None,'open_label_present':bool(value.get('OpenLabel')),'basket_present':value.get('Basket') is not None,'pending_label_present':bool(value.get('PendingLabel',value.get('NativePendingLabel',''))),'sending':value.get('Sending',False),'exit_pending':value.get('ExitPending',False),'batch_remaining':value.get('BatchRemaining',0),'last_bar_utc':value.get('LastBarUtc'),'last_signal_utc':value.get('LastSignalUtc',value.get('LastSignal')),'weekend_lock_until':value.get('WeekendLockUntil'),'peak_equity':value.get('Peak',value.get('PeakEquity'))})
  report['leases']=[{'role':k.split(':')[-1],'age_seconds':round(time.time()-t,2),'expires_in_seconds':round(e-time.time(),2)} for k,t,e in db.execute("SELECT key,touched_at,expires_at FROM bridge_leases WHERE key NOT LIKE 'TPPROBE:%'")]
 report['old_checkpoints']=[]
 oldstate=Path('/var/lib/rizan-buy050-bridge')
 if (oldstate/'checkpoints.sqlite').exists():
  with sqlite3.connect((oldstate/'checkpoints.sqlite').as_uri()+'?mode=ro',uri=True) as db:
   report['old_leases']=[{'role':k.split(':')[-1],'age_seconds':round(time.time()-t,2),'expires_in_seconds':round(e-time.time(),2)} for k,t,e in db.execute('SELECT key,touched_at,expires_at FROM bridge_leases')]
   for k,v,data in db.execute('SELECT key,version,state FROM checkpoints'):
    q=json.loads(data);report['old_checkpoints'].append({'symbol':k.split(':')[-1],'version':v,'basket_present':q.get('Basket') is not None,'pending_label_present':bool(q.get('PendingLabel',q.get('NativePendingLabel',''))),'sending':q.get('Sending',False),'exit_pending':q.get('ExitPending',False),'batch_active':q.get('BatchActive',False),'batch_remaining':q.get('BatchRemaining',0),'fault':q.get('Fault'),'quarantined':q.get('Quarantined')})
 report['vps']={'load':os.getloadavg(),'mem_available_kb':next((line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')),None)}
 r=subprocess.run(['systemctl','is-enabled','rizan-buy050-bridge.service'],capture_output=True,text=True);report['old_enabled']=r.stdout.strip()
 r=subprocess.run(['systemctl','is-enabled','rizan-bootstrap125-bridge.service'],capture_output=True,text=True);report['new_enabled']=r.stdout.strip()
 url='wss://rizan-bridge.duckdns.org:25345/bootstrap125/';lease=uuid.uuid4().hex;key='TPPROBE:'+PROFILE+':9000000000000000002:PROBE'
 async def opened():
  ws=await connect(url,open_timeout=15,close_timeout=5);await ws.send(json.dumps(dict(type='hello',token=env['BOOT125_BRIDGE_TOKEN'],key=key,lease=lease,contract=PROFILE)));r=json.loads(await asyncio.wait_for(ws.recv(),15));assert r['type']=='ready','PROBE_HANDSHAKE_FAILED';return ws,r
 ws,r=await opened();rev=(r.get('state') or {}).get('Revision',0)+1;payload=dict(Schema=1,ContractHash=PROFILE,AccountNumber=9000000000000000002,Symbol='PROBE',Revision=rev,ObservedUtc=datetime.now(timezone.utc).isoformat());await ws.send(json.dumps(dict(type='save',base_revision=r['revision'],client_revision=rev,state=payload)));ack=json.loads(await asyncio.wait_for(ws.recv(),15));assert ack['type']=='ack','PROBE_ACK_FAILED';await ws.close();await asyncio.sleep(.1)
 ws,r=await opened();assert r['state']==payload,'PROBE_READBACK_FAILED';await ws.send('{"type":"ping"}');assert json.loads(await asyncio.wait_for(ws.recv(),15))['type']=='pong','PROBE_PONG_FAILED';await ws.close()
 report['public_wss']={'authenticated':True,'durable_ack':True,'reconnect_readback':True,'heartbeat':True,'only_probe_namespace':True}
 report['tick_file_inventory']={}
 for sym in ['XAUUSD','EURUSD','BTCUSD']:
  root=Path('/home/Rizanrizan/rizan-ticks')/sym;fs=sorted(root.glob('2026/*.parquet'));report['tick_file_inventory'][sym]={'files_2026':[p.name for p in fs],'directory_exists':root.is_dir()}
 print(json.dumps(report,indent=2))
asyncio.run(main())

# Recheck requested before direct algo download, 2026-11-15.

# Post-deployment dependency and prior-instance audit.

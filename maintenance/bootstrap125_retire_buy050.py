"""Retire only the prior BUY050 bridge after validating live Bootstrap125 dependencies."""
import asyncio,json,os,shlex,sqlite3,subprocess,time,uuid,sys
from pathlib import Path
from datetime import datetime,timezone
from websockets.asyncio.client import connect
sys.path.insert(0,'/opt/rizan-bootstrap125-bridge')
from server import Store
NEW='rizan-bootstrap125-bridge.service';OLD='rizan-buy050-bridge.service';PROFILE='b6014ae7d456b10f88671f1e58e605509a20771386c72f3ca7ae8b210bde0128';ROLES={'BOOTSTRAP','EURUSD','XAUUSD','BTCUSD'}
def cmd(a):return subprocess.run(a,capture_output=True,text=True,check=True,timeout=30).stdout.strip()
def prop(unit,name):return cmd(['systemctl','show',unit,'--value','-p',name])
def envread():
 d={}
 for line in Path('/etc/rizan-bootstrap125-bridge.env').read_text().splitlines():
  if '=' in line and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);p=shlex.split(v);d[k.strip()]=p[0] if len(p)==1 else v
 return d
def conn(path):return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
def new_ok(folder):
 h=json.loads((folder/'health.json').read_text());age=time.time()-datetime.fromisoformat(h['observed_utc'].replace('Z','+00:00')).timestamp();assert 0<=age<45 and h['btc']=='ready' and h['macro_snapshot_present'],'NEW_FEEDS_NOT_FRESH'
 records={};leases={}
 with conn(folder/'checkpoints.sqlite') as db:
  for key,v,data in db.execute("SELECT key,version,state FROM checkpoints WHERE key NOT LIKE 'TPPROBE:%'"):
   s=json.loads(data);Store._validate_state_identity(key,s['Revision'],s);role=key.split(':')[-1];assert role not in records,'DUPLICATE_NEW_ROLE';assert not s.get('Fault') and not s.get('Quarantined'),'NEW_ROLE_FAULT'
   records[role]={'version':v,'client_revision':s['Revision'],'phase':s.get('Phase'),'graduation_balance':s.get('GraduationBalance'),'graduated_utc':s.get('GraduatedUtc'),'account_suffix':str(s['AccountNumber'])[-4:]}
  for key,t,e in db.execute("SELECT key,touched_at,expires_at FROM bridge_leases WHERE key NOT LIKE 'TPPROBE:%'"):
   if e>time.time() and time.time()-t<25:leases[key.split(':')[-1]]=t
 assert set(records)==ROLES and set(leases)==ROLES,'FOUR_NEW_ROLES_NOT_ALIVE'
 assert h['connected']>=4,'NEW_PEERS_NOT_FOUR'
 return records,leases,h
async def probe(env):
 url='wss://rizan-bridge.duckdns.org:25345/bootstrap125/';lease=uuid.uuid4().hex;key='TPPROBE:'+PROFILE+':9000000000000000003:PROBE'
 async with connect(url,open_timeout=15,close_timeout=5) as ws:
  await ws.send(json.dumps(dict(type='hello',key=key,lease=lease,contract=PROFILE,token=env['BOOT125_BRIDGE_TOKEN'])));r=json.loads(await asyncio.wait_for(ws.recv(),15));assert r['type']=='ready','NEW_WSS_FAILED';await ws.send('{"type":"ping"}');assert json.loads(await asyncio.wait_for(ws.recv(),15))['type']=='pong','NEW_WSS_HEARTBEAT_FAILED'
 return True
async def main():
 assert os.geteuid()==0,'ROOT_REQUIRED';env=envread();state=Path(env['BOOT125_STATE_DIR']);old=Path('/var/lib/rizan-buy050-bridge');start=prop(NEW,'ExecMainStartTimestampMonotonic');assert prop(NEW,'ActiveState')=='active','NEW_SERVICE_INACTIVE';records,leases,health=new_ok(state)
 paths=[state,Path(env['BOOT125_BTC_SEED']),state/'btc-m1.sqlite']
 assert all(p.exists() and '/rizan-buy050-bridge' not in str(p.resolve()) for p in paths),'NEW_DEPENDENCY_STILL_POINTS_TO_OLD'
 with conn(old/'checkpoints.sqlite') as db:
  for key,v,data in db.execute('SELECT key,version,state FROM checkpoints'):
   s=json.loads(data);assert s.get('Basket') is None and not s.get('PendingLabel') and not s.get('NativePendingLabel') and not s.get('Sending') and not s.get('ExitPending') and not s.get('BatchActive') and not s.get('BatchRemaining',0),'OLD_OPEN_OR_UNCERTAIN_STATE'
  assert not db.execute('SELECT 1 FROM bridge_leases WHERE expires_at>? AND touched_at>?',(time.time(),time.time()-30)).fetchone(),'OLD_INSTANCE_STILL_CONNECTED'
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup=Path('/var/backups/rizan-retired-buy050')/stamp;backup.mkdir(parents=True,mode=0o700)
 with conn(old/'checkpoints.sqlite') as src:
  with sqlite3.connect(backup/'checkpoints.sqlite') as dst:src.backup(dst)
 (backup/'checkpoints.sqlite').chmod(0o600)
 prior_enabled=prop(OLD,'UnitFileState');cmd(['systemctl','disable','--now',OLD])
 try:
  for i in range(7):
   await asyncio.sleep(2);after,after_leases,after_health=new_ok(state)
   if all(after_leases[k]>leases[k] for k in ROLES):break
  assert all(after_leases[k]>leases[k] for k in ROLES),'NEW_HEARTBEATS_DID_NOT_ADVANCE'
  assert prop(NEW,'ActiveState')=='active' and prop(NEW,'ExecMainStartTimestampMonotonic')==start,'NEW_SERVICE_CHANGED'
  assert prop(OLD,'ActiveState')=='inactive' and prop(OLD,'UnitFileState')=='disabled','OLD_SERVICE_NOT_RETIRED'
  await probe(env)
 except Exception:
  if prior_enabled=='enabled':cmd(['systemctl','enable',OLD])
  cmd(['systemctl','start',OLD]);raise
 report={'observed_utc':datetime.now(timezone.utc).isoformat(),'old_service':OLD,'old_active_state':prop(OLD,'ActiveState'),'old_unit_file_state':prop(OLD,'UnitFileState'),'old_state_preserved':True,'backup_path':str(backup),'new_service':NEW,'new_service_active':True,'new_service_not_restarted':True,'new_enabled':prop(NEW,'UnitFileState'),'new_heartbeat_roles':sorted(after_leases),'new_heartbeats_advanced':True,'new_checkpoints':after,'btc':after_health['btc'],'macro_snapshot_present':after_health['macro_snapshot_present'],'public_wss_heartbeat':True,'new_dependencies_independent':True,'broker_orders':0,'trading_state_writes':0,'config_trading_enabled_observable':False}
 maintenance=Path('/var/lib/rizan-maintenance');maintenance.mkdir(exist_ok=True,mode=0o700);p=maintenance/('retired-bridge-'+OLD+'-'+stamp+'.json');p.write_text(json.dumps(report,indent=2));p.chmod(0o600);print(json.dumps(report,indent=2))
try:asyncio.run(main())
except Exception as e:print(json.dumps({'retired':False,'error_type':type(e).__name__,'reason':str(e) if isinstance(e,AssertionError) else 'PRIVATE_DIAGNOSTICS_REDACTED'}));sys.exit(1)

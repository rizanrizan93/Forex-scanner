"""Read-only handoff preflight. No broker orders, credentials or checkpoint changes."""
import os,json,time,sqlite3,subprocess,shlex
from pathlib import Path
from datetime import datetime,timezone
def env(p):
 d={}
 for line in Path(p).read_text().splitlines():
  if '=' in line and not line.lstrip().startswith('#'):
   k,v=line.split('=',1);a=shlex.split(v);d[k]=a[0] if len(a)==1 else v
 return d
def run(a):return subprocess.run(a,capture_output=True,text=True,timeout=10).stdout.strip()
def dbro(p):return sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
def role_status(folder,account):
 now=time.time()
 with dbro(folder/'checkpoints.sqlite') as db:
  leases={k:(e,t) for k,e,t in db.execute('select key,expires_at,touched_at from bridge_leases')}
  result=[]
  for k,v,raw in db.execute('select key,version,state from checkpoints'):
   p=k.split(':')
   if len(p)<3 or p[-2]!=account:continue
   s=json.loads(raw);e,t=leases.get(k,(0,0))
   result.append(dict(role=p[-1],lease_active=e>now,lease_age_s=round(now-t,1) if t else None,phase=s.get('Phase'),xau_unlocked=s.get('XauUnlocked'),version=v,uncertain=any(s.get(k) for k in ('Basket','PendingLabel','NativePendingLabel','Sending','ExitPending','BatchActive','BatchRemaining','OpenLabel','Intent','HandoffSignal','Fault','Quarantined')),fault=bool(s.get('Fault') or s.get('Quarantined'))))
  return result
def health(folder):
 try:
  h=json.loads((folder/'health.json').read_text())
  return dict(age_s=round(time.time()-datetime.fromisoformat(h['observed_utc'].replace('Z','+00:00')).timestamp(),1),btc=h.get('btc'),macro=h.get('macro_snapshot_present'),connected=h.get('connected'))
 except Exception:return {}
v1=env('/etc/rizan-bootstrap125-bridge.env');v8=env('/etc/rizan-v8frozen-bridge.env')
accounts=[a.strip() for a in v1['BOOT125_ALLOWED_ACCOUNTS'].split(',') if a.strip().endswith('7903')]
assert len(accounts)==1,'LIVE_ACCOUNT_BINDING_NOT_UNIQUE'
a=accounts[0];f1=Path(v1['BOOT125_STATE_DIR']);f8=Path(v8['BOOT125_STATE_DIR'])
r1=role_status(f1,a);r8=role_status(f8,a)
p=Path('/var/lib/rizan-bootstrap125-monitor/broker.json')
broker={}
if p.is_file():
 b=json.loads(p.read_text())
 broker=dict(status=b.get('status'),age_s=round(time.time()-datetime.fromisoformat(b['observed_at'].replace('Z','+00:00')).timestamp(),1),open_positions=sum(r.get('open_positions',0) for r in b.get('roles',{}).values()),pending_orders=sum(r.get('pending_orders',0) for r in b.get('roles',{}).values()),foreign_exposure=b.get('foreign_exposure_present'))
print('V8_LIVE_PREFLIGHT '+json.dumps(dict(account_suffix=a[-4:],v1_active=run(['systemctl','is-active','rizan-bootstrap125-bridge.service']),v8_active=run(['systemctl','is-active','rizan-v8frozen-bridge.service']),v1_roles=r1,v8_live_roles=r8,v1_health=health(f1),v8_health=health(f8),v8_live_allowed=a in v8['BOOT125_ALLOWED_ACCOUNTS'].split(','),broker=broker,orders=0)))

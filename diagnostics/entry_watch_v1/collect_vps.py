"""Stream a read-only snapshot. No env/token reads, leases, database writes or imports of live services."""
import json,sqlite3,subprocess,time,hashlib
from pathlib import Path
from datetime import datetime,timezone

def clean(v):
    if isinstance(v,dict):
        result={}
        for k,x in v.items():
            if any(w in k.lower() for w in ['token','secret','password','lease']):continue
            if k in ['AccountNumber','ctidTraderAccountId']:
                result[k+'Suffix']=str(x)[-4:]
            else:result[k]=clean(x)
        return result
    if isinstance(v,list):return [clean(x) for x in v]
    return v

folder=Path('/var/lib/rizan-btc10-bridge')
out={'observed_utc':datetime.now(timezone.utc).isoformat(),
     'execution_authority':'NONE','errors':[],'checkpoints':[]}
health=folder/'health.json'
if health.exists():out['health']=clean(json.loads(health.read_text()))
p=folder/'checkpoints.sqlite'
if p.exists():
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.execute('PRAGMA query_only=ON')
        for key,version,state in db.execute('SELECT key,version,state FROM checkpoints'):
            out['checkpoints'].append({'server_version':version,'state':clean(json.loads(state))})
        out['receipts_schema']=[r[1] for r in db.execute('PRAGMA table_info(checkpoint_receipts)')]
        out['checkpoint_receipts_count']=db.execute('SELECT count(*) FROM checkpoint_receipts').fetchone()[0]
        out['leases']=[{'symbol':key.split(':')[-1],'age_seconds':time.time()-touched,
            'remaining_seconds':expiry-time.time()} for key,expiry,touched in
            db.execute('SELECT key,expires_at,touched_at FROM bridge_leases')]

# Exact feed source used by the frozen BTC cBot: pinned hourly seed plus M1 extension.
seed=Path('/opt/rizan-btc10-bridge/BTC_SEED_PACKET.json')
dbpath=folder/'btc-m1.sqlite'
if seed.exists() and dbpath.exists():
    packet=json.loads(seed.read_text());through=int(time.time())//3600*3600
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as db:
        db.execute('PRAGMA query_only=ON')
        rows=db.execute('SELECT at,o,h,l,c FROM minutes WHERE at>=? AND at<? ORDER BY at',
                        (packet['through'],through)).fetchall()
    hours=[];last=None;contiguous=True;expected=packet['through']
    for at,o,h,l,c in rows:
        if at!=expected:contiguous=False
        expected=at+60
        hour=at//3600*3600
        if last!=hour:hours.append([hour,o,h,l,c,1]);last=hour
        else:
            b=hours[-1];b[2]=max(b[2],h);b[3]=min(b[3],l);b[4]=c;b[5]+=1
    out['btc_feed']={'contract':packet['contract'],'source':packet['source'],
        'through':through,'bars':packet['bars']+hours,
        'extension_contiguous':contiguous and expected==through and all(b[5]==60 for b in hours)}
else:out['errors'].append('EXACT_BTC_FEED_FILES_UNAVAILABLE')

# Inspect only known application folders for durable macro/news evidence, never credentials.
out['macro_files']=[]
for root in [folder,Path('/opt/rizan-btc10-bridge')]:
    for p in root.glob('*.json'):
        if 'macro' in p.name.lower() or 'snapshot' in p.name.lower():
            if p.stat().st_size<500000:
                try:out['macro_files'].append({'name':p.name,'mtime':p.stat().st_mtime,
                    'data':clean(json.loads(p.read_text()))})
                except Exception:pass
out['limitations']=['Runtime EnableTrading/accountBound/status not persisted in these checkpoints',
 'Current checkpoint is not historical decision journal',
 'Absent macro snapshot file does not prove feed failure; server keeps snapshot in memory']
print(json.dumps(out,allow_nan=False),flush=True)

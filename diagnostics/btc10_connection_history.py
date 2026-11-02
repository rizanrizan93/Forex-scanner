"""Read-only connection history; omit client addresses, credentials and state bodies."""
from pathlib import Path
import collections,json,re,subprocess,time
from datetime import datetime,timezone
now=datetime.now(timezone.utc)
paths=[]
for p in Path('/var/log/nginx').glob('*access*.log'):
 if p.is_file():paths.append(p)
events=[]
for p in paths[:10]:
 with p.open('rb') as f:
  f.seek(max(0,p.stat().st_size-2000000));rows=f.read().decode(errors='replace').splitlines()
 for line in rows:
  m=re.search(r'\[([^]]+)\]\s+"(GET|HEAD)\s+(/btc10(?:/btc)?/?)\s+HTTP/[^\"]+"\s+(\d{3})\s+(\d+)',line)
  if not m:continue
  try:at=datetime.strptime(m[1],'%d/%b/%Y:%H:%M:%S %z').astimezone(timezone.utc)
  except ValueError:continue
  if (now-at).total_seconds()>10800:continue
  events.append({'utc':at.isoformat(),'path':m[3],'status':int(m[4]),'bytes':int(m[5])})
events.sort(key=lambda x:x['utc'])
print('CONNECTION_HISTORY='+json.dumps({'observed_utc':now.isoformat(),'window_hours':3,'files_checked':[p.name for p in paths[:10]],'totals':dict(collections.Counter(str(e['status']) for e in events)),'events':events[-60:]}),flush=True)
p=subprocess.run(['journalctl','-u','rizan-btc10-bridge.service','--since','-3 hours','--no-pager','-o','json','-n','400'],capture_output=True,text=True,timeout=20)
errors=[]
for line in p.stdout.splitlines():
 try:r=json.loads(line)
 except ValueError:continue
 message=r.get('MESSAGE','')
 kinds=[x for x in ['InvalidUpgrade','keepalive ping timeout','ConnectionClosedError','ConnectionClosedOK','TimeoutError','LEASE_BUSY','LEASE_EXPIRED','REVISION_CONFLICT','AUTH_FAILED','MemoryError','BrokenPipeError'] if x in message]
 if kinds:errors.append({'utc':datetime.fromtimestamp(int(r['__REALTIME_TIMESTAMP'])/1e6,timezone.utc).isoformat(),'kinds':kinds})
print('CONNECTION_ERRORS='+json.dumps(errors[-30:]),flush=True)

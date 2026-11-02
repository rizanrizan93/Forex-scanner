"""Read-only diagnostics; never acquire a cBot lease or submit broker requests."""
import asyncio,collections,hashlib,json,os,re,shutil,socket,sqlite3,subprocess,time
from pathlib import Path
from datetime import datetime,timezone

def run(args):
 p=subprocess.run(args,text=True,capture_output=True,timeout=20)
 return p.returncode,p.stdout
def report(label,data):print(label+'='+json.dumps(data,allow_nan=False),flush=True)

report('OBSERVED',{'utc':datetime.now(timezone.utc).isoformat(),'load':os.getloadavg(),'execution_authority':'NONE','mutations':0})
disk=shutil.disk_usage('/')
report('HOST',{'cpu_count':os.cpu_count(),'uptime_seconds':float(Path('/proc/uptime').read_text().split()[0]),'disk_total_gib':round(disk.total/2**30,2),'disk_free_gib':round(disk.free/2**30,2)})
code,text=run(['ps','-eo','pid,comm,pcpu,pmem,rss','--sort=-rss']);report('PROCESS_MEMORY',{'code':code,'top':text.splitlines()[:13]})
code,text=run(['systemctl','--failed','--no-pager','--no-legend']);report('FAILED_UNITS',{'code':code,'units':[l.split()[0] for l in text.splitlines() if l.strip()][:30]})
code,text=run(['journalctl','-k','--since','-2 hours','--no-pager','-o','cat','-n','500'])
report('KERNEL',{'code':code,'counts':{k:text.lower().count(k) for k in ['out of memory','oom-kill','killed process','i/o error','ext4-fs error','segfault']}})
code,text=run(['journalctl','-u','ssh.service','--since','-2 hours','--no-pager','-o','cat','-n','500'])
report('SSH_LOG_SUMMARY',{'code':code,'counts':{k:text.count(k) for k in ['Failed password','Accepted publickey','Accepted password','Invalid user','authentication failure','MaxStartups']}})
for unit in ['rizan-btc10-bridge.service','rizan-tp500-bridge.service','rizan-cbot-bridge.service','nginx.service']:
 code,text=run(['systemctl','show',unit,'--no-pager','-p','ActiveState','-p','SubState','-p','NRestarts','-p','ExecMainStartTimestamp','-p','MemoryCurrent','-p','CPUUsageNSec'])
 report('SERVICE',{'unit':unit,'code':code,**dict(x.split('=',1) for x in text.splitlines() if '=' in x)})
report('MEMORY',{k:v.strip() for k,v in (x.split(':',1) for x in Path('/proc/meminfo').read_text().splitlines()) if k in ['MemTotal','MemAvailable','SwapTotal','SwapFree']})
code,text=run(['ss','-ltn']);report('LISTENERS',{'code':code,'lines':[l for l in text.splitlines() if re.search(r':(?:25345|25350)\b',l)]})
folder=Path('/var/lib/rizan-btc10-bridge');health=folder/'health.json'
if health.exists():
 value=json.loads(health.read_text());report('HEALTH',{k:value.get(k) for k in ['profile','observed_utc','btc','macro_snapshot_present','connected','execution_authority']})
dbpath=folder/'checkpoints.sqlite'
if dbpath.exists():
 with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
  for key,version,raw in db.execute('SELECT key,version,state FROM checkpoints'):
   s=json.loads(raw);report('CHECKPOINT',{'symbol':s.get('Symbol'),'account_suffix':str(s.get('AccountNumber'))[-4:],'server_version':version,**{k:s.get(k) for k in ['Revision','Quarantined','QuarantineReason','Fault','ExitPending','Sending','BatchRemaining','NativePendingSequence','PendingChildren','LastBarUtc','LastSignalUtc']}})
  for key,expiry,touched in db.execute('SELECT key,expires_at,touched_at FROM bridge_leases'):
   report('LEASE',{'symbol':key.split(':')[-1],'age_seconds':round(time.time()-touched,2),'remaining_seconds':round(expiry-time.time(),2)})
code,text=run(['journalctl','-u','rizan-btc10-bridge.service','--since','-15 min','--no-pager','-o','cat','-n','250'])
codes=['TimeoutError','ConnectionClosedError','ConnectionClosedOK','Traceback','LEASE_BUSY','LEASE_EXPIRED','REVISION_CONFLICT','BrokenPipeError','MemoryError','connection handler failed','no close frame','keepalive ping timeout']
report('JOURNAL',{'code':code,'lines':len(text.splitlines()),'counts':{k:text.count(k) for k in codes if k in text}})
error=Path('/var/log/nginx/error.log')
if error.exists():
 with error.open('rb') as f:f.seek(max(0,error.stat().st_size-60000));lines=f.read().decode(errors='replace').splitlines()
 relevant=[l for l in lines if '25350' in l or '/btc10' in l]
 report('NGINX_ERRORS',{'relevant_tail_lines':len(relevant),'kinds':{k:sum(k in l for l in relevant) for k in ['upstream timed out','connect() failed','prematurely closed','no live upstreams','worker_connections are not enough']}})

async def probe(url):
 from websockets.asyncio.client import connect
 start=time.monotonic()
 try:
  async with connect(url,open_timeout=8,close_timeout=1) as ws:
   await ws.send('{"type":"hello"}')
   value=json.loads(await asyncio.wait_for(ws.recv(),5))
   return {'url':url,'reachable':True,'unauthenticated_rejected':value.get('code')=='AUTH_FAILED','seconds':round(time.monotonic()-start,2)}
 except Exception as e:return {'url':url,'reachable':False,'error_type':type(e).__name__,'seconds':round(time.monotonic()-start,2)}
async def main():
 for result in await asyncio.gather(probe('ws://127.0.0.1:25350/btc10/'),probe('wss://rizan-bridge.duckdns.org:25345/btc10/')):report('PROBE',result)
asyncio.run(main())

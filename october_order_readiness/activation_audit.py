"""Read-only service timeline, native checkpoints and bounded input-cache inventory."""
import datetime,json,pathlib,sqlite3,subprocess,time,sys,collections
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import lease_audit
P=pathlib.Path;BASE=P('/home/Rizanrizan/Forex-scanner')
UTC=datetime.timezone.utc
out={'observed_utc':datetime.datetime.now(UTC).isoformat(),'read_only':True,'services':{},'states':[],'native_bar_caches':[]}
for unit in ['rizan-cbot-bridge.service','rizan-btc7d130.service']:
 r=subprocess.run(['systemctl','show',unit,'--no-pager','-p','ActiveState','-p','ActiveEnterTimestamp','-p','ExecMainStartTimestamp','-p','NRestarts'],capture_output=True,text=True,timeout=15)
 props=dict(l.split('=',1) for l in r.stdout.splitlines() if '=' in l)
 # Do not export raw journal messages or any credentials, only timestamps and fixed marker counts.
 r=subprocess.run(['journalctl','-u',unit,'--since','2026-10-09 00:00:00 UTC','-n','40000','--no-pager','-o','json'],capture_output=True,text=True,timeout=25)
 markers=['Started','Starting','server listening','connection open','connection closed','AUTH_FAILED','LEASE_BUSY','IDENTITY_INVALID','FEED_NOT_CURRENT','M1_GAP','Traceback','Main process exited','BRIDGE_HANDSHAKE_OK','BTC_BRIDGE']
 events={k:[] for k in markers};records=0;first=None;last=None
 for line in r.stdout.splitlines():
  try:v=json.loads(line);at=datetime.datetime.fromtimestamp(int(v['__REALTIME_TIMESTAMP'])/1e6,UTC).isoformat();msg=str(v.get('MESSAGE',''))
  except Exception:continue
  first=first or at;last=at;records+=1
  for marker in markers:
   if marker in msg:events[marker].append(at)
 out['services'][unit]={'properties':props,'retained_journal_records':records,'first_retained_utc':first,'last_retained_utc':last,'markers':{k:{'count':len(v),'first_utc':v[0] if v else None,'last_utc':v[-1] if v else None} for k,v in events.items()}}
 env=lease_audit.env(unit)
 path=P(env.get('RZ7D_STATE_DB',env.get('RIZAN_STATE_DB','state/rizan-checkpoints.sqlite')))
 if not path.is_absolute():path=BASE/path
 if path.exists():
  c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON')
  for key,ver,raw in c.execute('SELECT key,version,state FROM checkpoints'):
   if unit=='rizan-cbot-bridge.service' and ':2147903:' not in key:continue
   s=json.loads(raw);fields=['EpochUtc','LastBarUtc','LastSignalUtc','LastRealExitUtc','PeakEquity','Quarantined','QuarantineReason','LastSignal','Fault','Sending','ExitPending','XauResumeUtc','Revision']
   out['states'].append({'unit':unit,'namespace':key.split(':')[0],'symbol':key.split(':')[-1],'server_revision':ver,'state':{k:s[k] for k in fields if k in s},'basket_present':s.get('Basket') is not None,'pending_label_present':bool(s.get('PendingLabel'))})
  c.close()
# Inventory only local bar-cache names; no env/token/database contents exported.
for root in [BASE/'state',P('/home/Rizanrizan/rizan-ticks')/'state']:
 if not root.exists():continue
 for p in root.rglob('*'):
  if not p.is_file() or len(p.relative_to(root).parts)>3:continue
  if any(k in p.name.lower() for k in ['candle','bar','ohlc','history']) and p.suffix in ['.json','.jsonl','.csv','.gz','.sqlite']:
   out['native_bar_caches'].append({'path':str(p),'bytes':p.stat().st_size})
print(json.dumps(out,indent=2))

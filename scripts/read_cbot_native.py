"""VPS reader: SQLite read-only + a separate in-memory copy of the BTC feed.

Outputs only fields needed by the manual monitor. No lease acquire, checkpoint
save, service restart, token output or cTrader request is possible here.
"""
import datetime,hashlib,json,pathlib,re,shlex,sqlite3,subprocess,sys,time
P=pathlib.Path;BASE=P('/home/Rizanrizan/Forex-scanner')
def prop(unit,name):
 return subprocess.run(['systemctl','show',unit,'--value','-p',name],capture_output=True,text=True,check=True,timeout=10).stdout.strip()
def env(unit):
 out={}
 for item in shlex.split(prop(unit,'Environment')):
  k,sep,v=item.partition('=')
  if sep:out[k]=v
 for name in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)',prop(unit,'EnvironmentFiles')):
  for line in P(name).read_text().splitlines():
   k,sep,v=line.partition('=');k=k.strip().removeprefix('export ')
   if sep and re.fullmatch('[A-Z_][A-Z0-9_]*',k):out[k]=v.strip().strip('\"\'')
 return out
def resolve(e,key,default):
 p=P(e.get(key,default));return p if p.is_absolute() else BASE/p
def main():
 e=env('rizan-cbot-bridge.service');out={'as_of':datetime.datetime.now(datetime.timezone.utc).isoformat(),'states':{},'macro':{},'read_only':True}
 db=resolve(e,'RIZAN_STATE_DB','state/rizan-checkpoints.sqlite')
 con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=5);con.execute('PRAGMA query_only=ON')
 fields=['ContractHash','EpochUtc','LastBarUtc','LastSignalUtc','LastRealExitUtc','XauResumeUtc','XauDay','XauDaySignals','Quarantined','QuarantineReason','Eur']
 for key,raw in con.execute('SELECT key,state FROM checkpoints'):
  parts=key.split(':')
  if len(parts)!=3 or not parts[1].endswith('7903') or parts[0] not in {'RZXRC1','RZEF245'}:continue
  binding=hashlib.sha256(parts[1].encode()).hexdigest()
  if out.get('account_binding') and out['account_binding']!=binding:raise ValueError('AMBIGUOUS_ACCOUNT_BINDING')
  out['account_binding']=binding
  state=json.loads(raw);s={k:state[k] for k in fields if k in state};s['pending_intent']=bool(state.get('PendingLabel'));s['has_basket']=bool(state.get('Basket'))
  out['states'][parts[-1]]=s
 con.close()
 snap=resolve(e,'RIZAN_SNAPSHOT_PATH','state/xau_macro_event_snapshot.json')
 if snap.is_file():
  s=json.loads(snap.read_text());out['macro']={k:s.get(k) for k in ['ProducedUtc','CoverageFromUtc','CoverageToUtc','ForexFactoryOk','BlsOk','Dgs10','Dfii10','Events']}
 if '--btc' in sys.argv:
  try:
   unit='rizan-btc7d130.service';wd=P(prop(unit,'WorkingDirectory'));be=env(unit)
   match=re.search(r'path=([^ ;}]+)',prop(unit,'ExecStart'))
   if not match or not P(match.group(1)).is_file():raise ValueError('BTC_INTERPRETER_UNAVAILABLE')
   seed=be.get('RZ7D_SEED_CSV',str(wd/'BITSTAMP_H1_SEED.csv'))
   code="import sys,time;sys.path.insert(0,sys.argv[1]);from server import Feed;f=Feed(sys.argv[2]);f.update(time.time());print(f.wire(time.time()))"
   child=subprocess.run([match.group(1),'-c',code,str(wd),seed],capture_output=True,text=True,check=True,timeout=110,cwd=wd)
   out['btc_feed']=json.loads(child.stdout)
  except Exception as exc:out['btc_feed_error']=type(exc).__name__
 print(json.dumps(out,allow_nan=False))
if __name__=='__main__':main()

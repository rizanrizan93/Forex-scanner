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
   unit='rizan-btc7d130.service';wd=P(prop(unit,'WorkingDirectory'));sys.path.insert(0,str(wd))
   from server import Feed
   seed=wd/'BITSTAMP_H1_SEED.csv';f=Feed(seed);f.update(time.time());out['btc_feed']=json.loads(f.wire(time.time()))
  except Exception:out['btc_feed_error']='FEED_UNAVAILABLE'
 print(json.dumps(out,allow_nan=False))
if __name__=='__main__':main()

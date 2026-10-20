"""Read-only production snapshot. Never writes state, env, services or orders."""
import ast,datetime,hashlib,json,os,re,shlex,sqlite3,subprocess,time
from pathlib import Path
ROOT=Path('/home/Rizanrizan/Forex-scanner');UNIT='rizan-cbot-bridge.service'
def prop(name):
 p=subprocess.run(['systemctl','show',UNIT,'--value','-p',name],capture_output=True,text=True,timeout=15,check=True);return p.stdout.strip()
def run():
 env={}
 for entry in shlex.split(prop('Environment')):
  k,sep,v=entry.partition('=')
  if sep:env[k]=v
 for name in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)',prop('EnvironmentFiles')):
  for line in Path(name).read_text().splitlines():
   k,sep,v=line.partition('=');k=k.strip().removeprefix('export ')
   if sep and re.fullmatch('[A-Z_][A-Z0-9_]*',k):env[k]=v.strip().strip('\"\'')
 out={'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True,'production_changes':False,'new_7d_service_installed':False,'service_active':prop('ActiveState')=='active'}
 sources={};contracts={}
 for name in ['server.py','feeds.py','timestamps.py']:
  p=ROOT/'cbot_bridge'/name
  if p.is_file():sources[name]=hashlib.sha256(p.read_bytes()).hexdigest()
 p=ROOT/'cbot_bridge/server.py'
 if p.exists():
  for node in ast.walk(ast.parse(p.read_text())):
   if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CONTRACTS' for t in node.targets):
    contracts=ast.literal_eval(node.value)
 out['source_sha256']=sources;out['supported_frozen_namespaces']={k:k in contracts for k in ['RZXRC1','RZEF245','RZBTC7D130']}
 db=Path(env.get('RIZAN_STATE_DB','state/rizan-checkpoints.sqlite'));db=db if db.is_absolute() else ROOT/db
 out['checkpoint_db_exists']=db.is_file();out['checkpoint_summary']=[]
 if db.is_file():
  con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
  for key,version,raw in con.execute('SELECT key,version,state FROM checkpoints'):
   prefix=key.split(':')[0]
   if prefix not in {'RZXRC1','RZEF245','RZBTC7D130','RZXA1','RZEU4B'}:continue
   s=json.loads(raw);item={'namespace':prefix,'symbol':key.split(':')[-1],'revision_server':version,'revision_client':s.get('Revision'),'quarantined':s.get('Quarantined',s.get('Fault')),'pending_intent':bool(s.get('PendingLabel') or s.get('Sending') or s.get('ExitPending'))}
   if prefix in contracts:item['contract_matches']=s.get('ContractHash')==contracts[prefix]['hash']
   out['checkpoint_summary'].append(item)
  con.close()
 hp=Path(env.get('RIZAN_HEALTH_PATH','state/cbot_bridge_health.json'));hp=hp if hp.is_absolute() else ROOT/hp
 if hp.is_file():
  h=json.loads(hp.read_text());out['health_age_seconds']=round(time.time()-h.get('observed_at_unix',0),3);out['execution_authority']=h.get('execution_authority');out['streams']={}
  for symbol in ['XAUUSD','EURUSD']:
   v=h.get('streams',{}).get(symbol,{});out['streams'][symbol]={k:v.get(k) for k in ['connected','macro_event_ready','execution_authority']}
 print(json.dumps(out,indent=2))
if __name__=='__main__':
 try:run()
 except Exception as exc:print(json.dumps({'read_only':True,'audit_complete':False,'error_type':type(exc).__name__}));raise SystemExit(1)

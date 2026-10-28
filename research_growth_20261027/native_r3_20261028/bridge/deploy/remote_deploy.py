"""R3-only VPS deployment; never print secrets or full account identifiers."""
from __future__ import annotations
import argparse,contextlib,fcntl,hashlib,json,os,re,shlex,shutil,socket,sqlite3,subprocess,tempfile,time
from pathlib import Path

OLD_UNIT='rizan-cbot-bridge.service'
NEW_UNIT='rizan-r3-bridge.service'
HOST='rizan-bridge.duckdns.org'

def run(args,*,check=True,timeout=60,env=None):
 r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout,env=env)
 if check and r.returncode:raise RuntimeError('COMMAND_FAILED:'+Path(args[0]).name)
 return r

def prop(unit,name):
 r=run(['systemctl','show',unit,'--value','-p',name],check=False)
 if r.returncode and unit==NEW_UNIT and name=='LoadState':return 'not-found'
 if r.returncode:raise RuntimeError('SYSTEMD_PROPERTY_FAILED')
 return r.stdout.strip()
def parse_env(text):
 result={}
 for line in text.splitlines():
  line=line.strip()
  if not line or line.startswith('#') or '=' not in line:continue
  key,_,value=line.partition('=');key=key.removeprefix('export ').strip()
  if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key):
   tokens=shlex.split(value,comments=True)
   if len(tokens)==1:result[key]=tokens[0]
 return result

def legacy_config():
 env={}
 for entry in shlex.split(prop(OLD_UNIT,'Environment')):
  if '=' in entry:
   k,v=entry.split('=',1);env[k]=v
 paths=re.findall(r'(\S+)\s+\(ignore_errors=(?:yes|no)\)',prop(OLD_UNIT,'EnvironmentFiles'))
 for path in paths:
  p=Path(path)
  if p.is_file():env.update(parse_env(p.read_text()))
 token=env.get('RIZAN_BRIDGE_TOKEN','')
 if len(token)<32:raise RuntimeError('EXISTING_BRIDGE_TOKEN_NOT_RESOLVED')
 root=Path(prop(OLD_UNIT,'WorkingDirectory'))
 if not root.is_absolute():raise RuntimeError('LEGACY_WORKDIR_INVALID')
 db=Path(env.get('RIZAN_STATE_DB','state/rizan-checkpoints.sqlite'))
 if not db.is_absolute():db=root/db
 if not db.is_file():raise RuntimeError('LEGACY_STATE_DB_NOT_FOUND')
 accounts=set()
 with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as conn:
  for key,text in conn.execute('SELECT key,state FROM checkpoints'):
   pieces=key.split(':')
   if len(pieces)!=3 or pieces[0] not in {'RZXA1','RZXRC1','RZEU4B','RZEF245'}:continue
   state=json.loads(text);number=pieces[1]
   if re.fullmatch(r'[1-9][0-9]{0,18}',number) and str(state.get('AccountNumber'))==number and state.get('Symbol')==pieces[2]:accounts.add(number)
 if not accounts:raise RuntimeError('NO_REGISTERED_CBOT_ACCOUNT')
 return env,token,accounts

# Tokenizer preserves quoted strings/comments and finds only actual server blocks.
LEX=re.compile(r'#[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{};]|[^\s{};]+')
def server_blocks(text):
 tokens=[m for m in LEX.finditer(text) if not m.group().startswith('#')];out=[]
 for i,tok in enumerate(tokens[:-1]):
  if tok.group()!='server' or tokens[i+1].group()!='{':continue
  depth=1;j=i+2
  while j<len(tokens) and depth:
   depth+=1 if tokens[j].group()=='{' else -1 if tokens[j].group()=='}' else 0;j+=1
  if depth:raise RuntimeError('NGINX_UNBALANCED')
  inner=tokens[i+2:j-1];direct=[];current=[];nested=0
  for item in inner:
   word=item.group()
   if word=='{':nested+=1;current=[]
   elif word=='}':nested-=1;current=[]
   elif nested==0:
    if word==';':direct.append(current);current=[]
    else:current.append(word.strip('"\''))
  listening=any(d and d[0]=='listen' and any(re.search(r'(?:^|:)25345$',w) for w in d[1:]) for d in direct)
  names=[w for d in direct if d and d[0]=='server_name' for w in d[1:]]
  if listening and HOST in names:out.append((tok.start(),tokens[j-1].start(),direct))
 return out

def nginx_target():
 text=run(['nginx','-T']).stdout
 paths=re.findall(r'^# configuration file ([^\n]+):$',text,re.M)
 found=[]
 for path in dict.fromkeys(paths):
  p=Path(path)
  if p.is_file():
   blocks=server_blocks(p.read_text())
   for b in blocks:found.append((p,b))
 if len(found)!=1:raise RuntimeError('NGINX_TLS_SERVER_NOT_UNIQUE')
 return found[0]

def summary():
 _,token,accounts=legacy_config();target,_=nginx_target()
 return {'legacy_service_active':prop(OLD_UNIT,'ActiveState')=='active','legacy_token_resolved':len(token)>=32,'registered_account_count':len(accounts),'nginx_tls_server_found':True,'nginx_config':str(target),'new_service_present':prop(NEW_UNIT,'LoadState')!='not-found','public_host':HOST,'execution_authority':'NONE','broker_orders':0}

def atomic(path,data,mode=0o600):
 path=Path(path);fd,name=tempfile.mkstemp(prefix='.'+path.name+'.r3.',dir=path.parent)
 try:
  os.fchmod(fd,mode)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
 finally:
  with contextlib.suppress(FileNotFoundError):os.unlink(name)

def deploy(source):
 if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
 pre=summary();_,token,accounts=legacy_config();oldpid=prop(OLD_UNIT,'MainPID')
 if not pre['legacy_service_active']:raise RuntimeError('LEGACY_BRIDGE_NOT_ACTIVE')
 if pre['new_service_present'] or Path('/etc/rizan-r3-bridge.env').exists() or Path('/opt/rizan-r3-bridge').exists():raise RuntimeError('R3_ALREADY_EXISTS_PRESERVE_EXISTING_STATE')
 with socket.socket() as sock:sock.bind(('127.0.0.1',25347))
 target,block=nginx_target();oldconf=target.read_bytes();text=oldconf.decode();snippet=Path('/etc/nginx/rizan-r3-locations.conf')
 if snippet.exists() or re.search(r'location\s+(?:=\s+|\^~\s+)?/r3\b',text):raise RuntimeError('R3_ROUTE_ALREADY_EXISTS')
 # Install a new service only. Original code, config, tokens and checkpoints stay intact.
 if run(['getent','passwd','rizan-r3'],check=False).returncode==0:raise RuntimeError('R3_USER_ALREADY_EXISTS')
 run(['useradd','--system','--user-group','--home-dir','/var/lib/rizan-r3-bridge','--shell','/usr/sbin/nologin','rizan-r3'])
 dest=Path('/opt/rizan-r3-bridge');dest.mkdir(mode=0o755)
 for p in source.glob('*.py'):shutil.copy2(p,dest/p.name);os.chmod(dest/p.name,0o644)
 for name in ['requirements.txt','BTC_SEED_PACKET.json']:shutil.copy2(source/name,dest/name);os.chmod(dest/name,0o644)
 run(['python3','-m','venv',str(dest/'.venv')]);run([str(dest/'.venv/bin/python'),'-m','pip','install','--disable-pip-version-check','-r',str(dest/'requirements.txt')],timeout=360)
 conf='R3_HOST=127.0.0.1\nR3_PORT=25347\nR3_STATE_DIR=/var/lib/rizan-r3-bridge\nR3_BTC_SEED=/opt/rizan-r3-bridge/BTC_SEED_PACKET.json\nR3_ALLOWED_ACCOUNTS='+','.join(sorted(accounts))+'\nR3_BRIDGE_TOKEN='+token+'\n'
 atomic('/etc/rizan-r3-bridge.env',conf.encode())
 unit=Path('/etc/systemd/system')/NEW_UNIT;atomic(unit,(source/'deploy'/NEW_UNIT).read_bytes(),0o644)
 run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',NEW_UNIT])
 for _ in range(30):
  try:
   with socket.create_connection(('127.0.0.1',25347),timeout=1):break
  except OSError:time.sleep(1)
 else:raise RuntimeError('R3_BACKEND_NOT_READY')
 if prop(NEW_UNIT,'ActiveState')!='active':raise RuntimeError('R3_SERVICE_NOT_ACTIVE')
 # Add one include to the existing TLS server; preserve every original byte otherwise.
 timestamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());backup=target.with_name(target.name+'.r3-backup-'+timestamp);shutil.copy2(target,backup)
 snippet_bytes=(source/'deploy/nginx-r3-locations.conf').read_bytes();atomic(snippet,snippet_bytes,0o644)
 updated=text[:block[1]]+'    include /etc/nginx/rizan-r3-locations.conf;\n'+text[block[1]:]
 try:
  atomic(target,updated.encode(),target.stat().st_mode&0o777)
  run(['nginx','-t']);run(['systemctl','reload','nginx'])
 except Exception:
  atomic(target,oldconf,backup.stat().st_mode&0o777);run(['nginx','-t']);run(['systemctl','reload','nginx']);snippet.unlink(missing_ok=True);raise
 if prop(OLD_UNIT,'MainPID')!=oldpid:raise RuntimeError('LEGACY_PID_CHANGED_DURING_DEPLOY')
 report={'deployment':'installed','R3_service_active':True,'legacy_service_pid_unchanged':True,'registered_account_count':len(accounts),'authentication':'existing private bridge token reused without display','macro_url':'wss://'+HOST+':25345/r3/','btc_url':'wss://'+HOST+':25345/r3/btc','new_checkpoint_namespace':True,'broker_orders':0,'main_branch_changed':False,'data_readiness':'pending_authenticated_probe'}
 atomic('/var/lib/rizan-r3-bridge/deploy-report.json',json.dumps(report,indent=2).encode())
 print(json.dumps(report,indent=2))
 # Order-free public TLS/auth/heartbeat/feed probe. Do not put accounts/token in logs.
 env=os.environ.copy();env.update(R3_PUBLIC_URL='wss://'+HOST+':25345/r3',R3_BRIDGE_TOKEN=token,R3_PROBE_ACCOUNT=sorted(accounts)[0])
 for attempt in range(8):
  result=run([str(dest/'.venv/bin/python'),str(dest/'probe.py')],check=False,timeout=90,env=env)
  if result.returncode==0:
   report['data_readiness']='authenticated_public_probe_pass';print(result.stdout);break
  if attempt==7:
   report['data_readiness']='not_ready';print('PUBLIC_PROBE_NOT_READY: '+result.stdout[-3000:]);print('Keep cBot order switch OFF until feed/probe passes.')
  else:time.sleep(20)
 report['legacy_service_pid_unchanged']=prop(OLD_UNIT,'MainPID')==oldpid
 atomic('/var/lib/rizan-r3-bridge/deploy-report.json',json.dumps(report,indent=2).encode());print(json.dumps(report,indent=2))
 if report['data_readiness']!='authenticated_public_probe_pass':raise RuntimeError('DEPLOYED_BUT_PUBLIC_DATA_NOT_READY')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['audit','deploy'],required=True);parser.add_argument('--source',type=Path,required=True);args=parser.parse_args()
 try:
  if args.mode=='audit':print(json.dumps(summary(),indent=2))
  else:
   with open('/var/lock/rizan-r3-deploy.lock','w') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);deploy(args.source.resolve())
 except Exception as ex:
  # Exception messages from third-party/environment paths may contain private config.
  safe=str(ex) if isinstance(ex,RuntimeError) and re.fullmatch(r'[A-Z_]+(?::[A-Za-z0-9_.-]+)?',str(ex)) else type(ex).__name__
  print('R3_DEPLOY_ERROR:'+safe);raise SystemExit(1)

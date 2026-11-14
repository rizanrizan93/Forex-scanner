"""Install an isolated service; preserve every legacy service PID/start time and checkpoint."""
from pathlib import Path
import os,sys,subprocess,shlex,re,socket,sqlite3,shutil,hashlib,time,json
UNIT='rizan-bootstrap125-bridge.service';USER='rizan-bootstrap125';APP=Path('/opt/rizan-bootstrap125-bridge');STATE=Path('/var/lib/rizan-bootstrap125-bridge');ENV=Path('/etc/rizan-bootstrap125-bridge.env');OLDENV=Path('/etc/rizan-buy050-bridge.env')
def run(a,**kw):return subprocess.run(a,check=True,text=True,capture_output=True,**kw)
def envparse(text):
 out={}
 for line in text.splitlines():
  if line.strip() and not line.lstrip().startswith('#') and '=' in line:
   k,v=line.split('=',1);p=shlex.split(v.strip());out[k.strip()]=p[0] if len(p)==1 else v.strip()
 return out
def services():
 units=run(['systemctl','list-units','--type=service','--state=active','--no-legend','--plain']).stdout
 names=[x.split()[0] for x in units.splitlines() if x.split() and x.split()[0].startswith('rizan-') and x.split()[0]!=UNIT]
 return {u:run(['systemctl','show',u,'--value','-p','ExecMainStartTimestampMonotonic']).stdout.strip() for u in names}
def mask(text):
 out=list(text);q=None;comment=False;escape=False
 for i,c in enumerate(text):
  if comment:
   if c=='\n':comment=False
   else:out[i]=' '
  elif q:
   out[i]=' '
   if escape:escape=False
   elif c=='\\':escape=True
   elif c==q:q=None
  elif c=='#':comment=True;out[i]=' '
  elif c in "\"'":q=c;out[i]=' '
 return ''.join(out)
def server_close(text):
 s=mask(text);found=[]
 for m in re.finditer(r'\bserver\s*\{',s):
  start=m.end()-1;i=start+1;depth=1
  while i<len(s) and depth:depth+=(s[i]=='{')-(s[i]=='}');i+=1
  if depth:raise RuntimeError('NGINX_UNBALANCED')
  if re.search(r'\blisten\s+[^;]*\b25345\b',s[start:i]):found.append(i-1)
 if len(found)>1:raise RuntimeError('NGINX_AMBIGUOUS_TLS_SERVER')
 return found[0] if found else None
def main():
 if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
 source=Path(__file__).resolve().parents[1];before=services()
 if 'rizan-buy050-bridge.service' not in before:raise RuntimeError('LIVE_BRIDGE_MUST_BE_HEALTHY_BEFORE_INSTALL')
 mem=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text()).group(1))
 if mem<300*1024:raise RuntimeError('INSUFFICIENT_AVAILABLE_MEMORY_FOR_ISOLATED_SERVICE')
 old=envparse(OLDENV.read_text());token=old.get('BUY050_BRIDGE_TOKEN','');accounts=old.get('BUY050_ALLOWED_ACCOUNTS','')
 if len(token)<32 or not accounts or any(not x.strip().isdigit() for x in accounts.split(',')):raise RuntimeError('EXISTING_SECURE_CONFIGURATION_REQUIRED')
 seed=Path(old.get('BUY050_BTC_SEED','/opt/rizan-buy050-bridge/BTC_SEED_PACKET.json'));cache=Path(old.get('BUY050_STATE_DIR','/var/lib/rizan-buy050-bridge'))/'btc-m1.sqlite'
 if not seed.is_file() or not cache.is_file():raise RuntimeError('EXISTING_PUBLIC_BTC_DATA_REQUIRED')
 if hashlib.sha256(seed.read_bytes()).hexdigest()!='210b1855ac5ffab2b628a7b4d301290427dc04e86a4a6042599d6d0ac8b873f2':raise RuntimeError('BTC_SEED_HASH_MISMATCH')
 nginx=run(['nginx','-T']).stdout;matches=[]
 for p in {Path(p).resolve() for p in re.findall(r'^# configuration file ([^:]+):$',nginx,re.M)}:
  if p.is_file():
   text=p.read_text();end=server_close(text)
   if end is not None:matches.append((p,text,end))
 if len(matches)!=1:raise RuntimeError('NGINX_TARGET_NOT_UNIQUE')
 conf,original,end=matches[0];snippet=Path('/etc/nginx/snippets/rizan-bootstrap125-locations.conf')
 exists=APP.exists() or ENV.exists() or Path('/etc/systemd/system',UNIT).exists()
 if exists:
  if not all(p.exists() for p in [APP,ENV,Path('/etc/systemd/system',UNIT),snippet]) or str(snippet) not in original:raise RuntimeError('PARTIAL_INSTALL_PRESERVED_NEEDS_REVIEW')
  existing=envparse(ENV.read_text())
  if existing.get('BOOT125_BRIDGE_TOKEN')!=token:raise RuntimeError('TOKEN_CHANGED_REVIEW_REQUIRED')
 else:
  if '/bootstrap125' in nginx or snippet.exists():raise RuntimeError('ROUTE_ALREADY_PRESENT')
  with socket.socket() as s:s.bind(('127.0.0.1',25356))
  if subprocess.run(['id','-u',USER],capture_output=True).returncode:run(['useradd','--system','--user-group','--home-dir',str(STATE),'--shell','/usr/sbin/nologin',USER])
  STATE.mkdir(mode=0o700,exist_ok=True)
  with sqlite3.connect(cache.resolve().as_uri()+'?mode=ro',uri=True) as db:
   with sqlite3.connect(STATE/'btc-m1.sqlite') as dst:db.backup(dst)
  APP.mkdir(mode=0o755)
  for p in source.iterdir():
   if p.is_file() and (p.suffix=='.py' or p.name=='requirements.txt'):shutil.copyfile(p,APP/p.name)
  shutil.copyfile(seed,APP/'BTC_SEED_PACKET.json')
  run(['python3','-m','venv',str(APP/'.venv')]);run([str(APP/'.venv/bin/pip'),'install','--disable-pip-version-check','-r',str(APP/'requirements.txt')])
  for p in [STATE,STATE/'btc-m1.sqlite']:shutil.chown(p,user=USER,group=USER);p.chmod(0o700 if p.is_dir() else 0o600)
  with ENV.open('x') as f:f.write('BOOT125_HOST=127.0.0.1\nBOOT125_PORT=25356\nBOOT125_STATE_DIR='+str(STATE)+'\nBOOT125_BTC_SEED='+str(APP/'BTC_SEED_PACKET.json')+'\nBOOT125_ALLOWED_ACCOUNTS='+accounts+'\nBOOT125_BRIDGE_TOKEN='+token+'\n')
  ENV.chmod(0o600);shutil.copyfile(source/'deploy'/UNIT,Path('/etc/systemd/system')/UNIT)
  backup=Path('/var/backups/rizan-bootstrap125')/str(int(time.time()));backup.mkdir(parents=True,mode=0o700);shutil.copyfile(conf,backup/'nginx-original.conf')
  run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',UNIT]);run(['systemctl','is-active','--quiet',UNIT])
  if conf.read_text()!=original:run(['systemctl','stop',UNIT]);raise RuntimeError('NGINX_CHANGED_DURING_INSTALL')
  snippet.parent.mkdir(exist_ok=True);shutil.copyfile(source/'deploy/nginx-bootstrap125-locations.conf',snippet)
  try:
   conf.write_text(original[:end]+'\n    include '+str(snippet)+';\n'+original[end:]);run(['nginx','-t']);run(['systemctl','reload','nginx'])
  except Exception:
   conf.write_text(original);snippet.unlink(missing_ok=True);run(['systemctl','stop',UNIT]);raise
 # Only our own service can be updated/restarted on an idempotent subsequent run.
 if exists:
  for p in source.iterdir():
   if p.is_file() and p.suffix=='.py':shutil.copyfile(p,APP/p.name)
  shutil.copyfile(source/'deploy'/UNIT,Path('/etc/systemd/system')/UNIT);run(['systemctl','daemon-reload']);run(['systemctl','restart',UNIT])
 run(['systemctl','is-active','--quiet',UNIT]);after=services()
 if any(after.get(k)!=v for k,v in before.items()):raise RuntimeError('LEGACY_SERVICE_CHANGED')
 env=os.environ.copy();env.update(envparse(ENV.read_text()))
 result=None
 for attempt in range(6):
  p=subprocess.run([str(APP/'.venv/bin/python'),str(source/'deploy/probe.py')],env=env,text=True,capture_output=True,timeout=90)
  if p.returncode==0:result=json.loads(p.stdout);break
  time.sleep(5)
 if result is None:raise RuntimeError('PUBLIC_WSS_PROBE_FAILED')
 report=dict(deployed=True,profile='RIZAN_BOOTSTRAP125_V1_FROZEN_20261114',service=UNIT,legacy_services_unchanged=True,legacy_service_count=len(before),server_sha256=hashlib.sha256((APP/'server.py').read_bytes()).hexdigest(),verification=result,observed_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),broker_orders=0)
 report_path=STATE/'deployment-verification.json';report_path.write_text(json.dumps(report,indent=2));report_path.chmod(0o600);print(json.dumps(report,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as e:print('BOOT125_DEPLOY_FAILED:'+type(e).__name__+':'+(str(e) if isinstance(e,RuntimeError) else 'private_diagnostics_redacted'));sys.exit(1)

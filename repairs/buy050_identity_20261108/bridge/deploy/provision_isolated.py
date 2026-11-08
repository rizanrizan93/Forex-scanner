"""Install only the new compression service and additive WSS route; never restart old cBots/bridge."""
from pathlib import Path
import os,re,json,sys,shlex,sqlite3,subprocess,shutil,time,socket,hashlib,gzip
UNIT='rizan-buy050-bridge.service';OLD='rizan-btc10-bridge.service';TARGET=Path('/opt/rizan-buy050-bridge');ENV=Path('/etc/rizan-buy050-bridge.env');STATE=Path('/var/lib/rizan-buy050-bridge')
def run(args,**kw):return subprocess.run(args,check=True,text=True,capture_output=True,**kw)
def prop(name):return run(['systemctl','show',OLD,'--value','-p',name]).stdout.strip()
def envparse(text):
 result={}
 for line in text.splitlines():
  if line.strip() and not line.lstrip().startswith('#') and '=' in line:
   k,v=line.split('=',1);parts=shlex.split(v.strip());result[k.strip()]=parts[0] if len(parts)==1 else v.strip()
 return result
def inherited():
 out={}
 for setting in shlex.split(prop('Environment')):
  if '=' in setting:k,v=setting.split('=',1);out[k]=v
 for p in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)',prop('EnvironmentFiles')):out.update(envparse(Path(p).read_text()))
 return out
def mask_config(text):
 out=list(text);quote=None;comment=False;escaped=False
 for i,c in enumerate(text):
  if comment:
   if c=='\n':comment=False
   else:out[i]=' '
  elif quote:
   out[i]=' '
   if escaped:escaped=False
   elif c=='\\':escaped=True
   elif c==quote:quote=None
  elif c=='#':comment=True;out[i]=' '
  elif c in "\"'":quote=c;out[i]=' '
 return ''.join(out)
def tls_server_close(text):
 masked=mask_config(text);matches=[]
 for m in re.finditer(r'\bserver\s*\{',masked):
  start=m.end()-1;depth=1;i=start+1
  while i<len(masked) and depth:
   depth+=(masked[i]=='{')-(masked[i]=='}');i+=1
  if depth:raise RuntimeError('NGINX_UNBALANCED_CONFIG')
  if re.search(r'\blisten\s+[^;]*\b25345\b',masked[start:i]):matches.append(i-1)
 if len(matches)>1:raise RuntimeError('NGINX_MULTIPLE_25345_SERVERS')
 return matches[0] if matches else None
def main():
 if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
 source=Path(__file__).resolve().parents[1];oldstart=prop('ExecMainStartTimestampMonotonic');oldstate=prop('ActiveState');prior={u:run(['systemctl','show',u,'--value','-p','ExecMainStartTimestampMonotonic']).stdout.strip() for u in ['rizan-cbot-bridge.service','rizan-compression-bridge.service','rizan-tp500-bridge.service','rizan-btc10-bridge.service']}
 if ENV.exists() or TARGET.exists() or Path('/etc/systemd/system/'+UNIT).exists():raise RuntimeError('ISOLATED_INSTALL_ALREADY_EXISTS_PRESERVE_STATE')
 old=inherited();token=old.get('R3_BRIDGE_TOKEN','')
 if len(token)<32:raise RuntimeError('EXISTING_BRIDGE_TOKEN_UNAVAILABLE')
 accounts={a.strip() for a in old.get('R3_ALLOWED_ACCOUNTS','').split(',') if a.strip().isdigit() and a.strip().endswith('7903')}
 if len(accounts)!=1:raise RuntimeError('CURRENT_7903_ACCOUNT_NOT_UNIQUE')
 account=next(iter(accounts))
 with socket.socket() as s:s.bind(('127.0.0.1',25352))
 nginx=run(['nginx','-T']).stdout;paths={Path(p).resolve() for p in re.findall(r'^# configuration file ([^:]+):$',nginx,re.M)};candidates=[]
 for p in paths:
  if not p.is_file():continue
  content=p.read_text();end=tls_server_close(content)
  if end is not None:candidates.append((p,content,end))
 if len(candidates)!=1:raise RuntimeError('NGINX_25345_SERVER_NOT_UNIQUE')
 conf,original,end=candidates[0];snippet=Path('/etc/nginx/snippets/rizan-buy050-locations.conf')
 if '/buy050' in original or snippet.exists():raise RuntimeError('BUY050_ROUTE_ALREADY_PRESENT_REVIEW_REQUIRED')
 run(['python3','-c','import sys; assert sys.version_info >= (3,11)'])
 run(['groupadd','--system','rizan-buy050']);run(['useradd','--system','--gid','rizan-buy050','--home-dir',str(STATE),'--shell','/usr/sbin/nologin','rizan-buy050'])
 # Copy data only using SQLite's consistent online backup API. Never import
 # checkpoints, leases, tokens or order activity into the fresh namespace.
 STATE.mkdir(mode=0o700)
 cached=Path(old.get('R3_STATE_DIR','/var/lib/rizan-btc10-bridge'))/'btc-m1.sqlite'
 if not cached.is_file():raise RuntimeError('BTC_DATA_CACHE_REQUIRED')
 with sqlite3.connect(cached.resolve().as_uri()+'?mode=ro',uri=True) as db:
  with sqlite3.connect(STATE/'btc-m1.sqlite') as dst:db.backup(dst)
 shutil.chown(STATE,user='rizan-buy050',group='rizan-buy050');shutil.chown(STATE/'btc-m1.sqlite',user='rizan-buy050',group='rizan-buy050');(STATE/'btc-m1.sqlite').chmod(0o600)
 TARGET.mkdir(mode=0o755)
 for p in source.iterdir():
  if p.is_file() and (p.suffix=='.py' or p.name in {'requirements.txt','BTC_SEED_PACKET.json.gz'}):shutil.copyfile(p,TARGET/p.name)
 seed_gz=TARGET/'BTC_SEED_PACKET.json.gz'
 seed_path=TARGET/'BTC_SEED_PACKET.json'
 with gzip.open(seed_gz,'rb') as fi,seed_path.open('wb') as fo:shutil.copyfileobj(fi,fo)
 if hashlib.sha256(seed_path.read_bytes()).hexdigest()!='210b1855ac5ffab2b628a7b4d301290427dc04e86a4a6042599d6d0ac8b873f2':raise RuntimeError('SEED_INTEGRITY_MISMATCH')
 seed_gz.unlink()
 run(['python3','-m','venv',str(TARGET/'.venv')]);run([str(TARGET/'.venv/bin/pip'),'install','--disable-pip-version-check','-r',str(TARGET/'requirements.txt')])
 with ENV.open('x') as f:f.write('BUY050_HOST=127.0.0.1\nBUY050_PORT=25352\nBUY050_STATE_DIR='+str(STATE)+'\nBUY050_BTC_SEED='+str(TARGET/'BTC_SEED_PACKET.json')+'\nBUY050_ALLOWED_ACCOUNTS='+account+'\nBUY050_BRIDGE_TOKEN='+token+'\n')
 ENV.chmod(0o600);shutil.copyfile(source/'deploy'/UNIT,Path('/etc/systemd/system')/UNIT)
 run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',UNIT]);run(['systemctl','is-active','--quiet',UNIT])
 backup=Path('/var/backups/rizan-buy050')/str(int(time.time()));backup.mkdir(parents=True,mode=0o700);shutil.copyfile(conf,backup/'nginx-original.conf')
 if conf.read_text()!=original:raise RuntimeError('NGINX_CHANGED_DURING_DEPLOY_REVIEW_REQUIRED')
 snippet.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/'deploy/nginx-buy050-locations.conf',snippet)
 try:
  conf.write_text(original[:end]+'\n    include '+str(snippet)+';\n'+original[end:]);run(['nginx','-t']);run(['systemctl','reload','nginx'])
 except Exception:
  conf.write_text(original);snippet.unlink(missing_ok=True);run(['systemctl','stop',UNIT]);raise
 if any(run(['systemctl','show',u,'--value','-p','ExecMainStartTimestampMonotonic']).stdout.strip()!=v for u,v in prior.items()) or prop('ActiveState')!=oldstate or prop('ExecMainStartTimestampMonotonic')!=oldstart:raise RuntimeError('EXISTING_BRIDGE_STATE_CHANGED')
 env=os.environ.copy();env.update(envparse(ENV.read_text()),BUY050_PUBLIC_URL='wss://rizan-bridge.duckdns.org:25345/buy050',BUY050_PROBE_ACCOUNT=account)
 # Authentication/heartbeat must succeed; external data may require a separate warmup.
 for attempt in range(12):
  probe=subprocess.run([str(TARGET/'.venv/bin/python'),str(TARGET/'probe.py')],env=env,text=True,capture_output=True)
  if probe.returncode==0:break
  time.sleep(10)
 report={'deployed':True,'service':UNIT,'old_bridge_not_restarted':True,'previous_compression_bridge_not_restarted':True,'profile':'RIZAN_BUY050_FROZEN_20261107','server_sha256':__import__('hashlib').sha256((TARGET/'server.py').read_bytes()).hexdigest(),'account_suffix':'7903','public_wss':'wss://rizan-bridge.duckdns.org:25345/buy050/','probe_pass':probe.returncode==0,'probe_output':probe.stdout[-5000:],'previous_tp500_bridge_not_restarted':True,'previous_disp1506_bridge_not_restarted':True,'observed_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'token_printed':False,'broker_orders':0}
 print(json.dumps(report,indent=2));Path('/var/lib/rizan-buy050-bridge/deployment-verification.json').write_text(json.dumps(report,indent=2))
 if probe.returncode:raise RuntimeError('ISOLATED_BRIDGE_DEPLOYED_BUT_FEED_OR_PUBLIC_PROBE_NOT_READY')
if __name__=='__main__':
 try:main()
 except Exception as e:print('BUY050_DEPLOY_FAILED:'+type(e).__name__+':'+(str(e) if isinstance(e,RuntimeError) else 'see_private_server_diagnostics'));sys.exit(1)

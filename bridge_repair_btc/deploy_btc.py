"""Add BTC-only backend/route. No orders; no cBot or primary bridge restart."""
import argparse,asyncio,grp,hashlib,json,os,pathlib,pwd,re,shlex,shutil,sqlite3,subprocess,sys,time
P=pathlib.Path
HOME=P('/home/Rizanrizan');ROOT=HOME/'rizan-btc7d130';MAIN=HOME/'Forex-scanner';UNIT='rizan-btc7d130.service'
ACCOUNT='2147903';ROUTE=P('/etc/nginx/conf.d/rizan-wss.conf')

def cmd(args,**kw):
 p=subprocess.run(args,capture_output=True,text=True,timeout=kw.pop('timeout',60),**kw)
 if p.returncode:raise RuntimeError('COMMAND_FAILED_'+P(args[0]).name)
 return p.stdout.strip()

def prop(name):return cmd(['systemctl','show','rizan-cbot-bridge.service','--value','-p',name])
def environment():
 env=dict(x.split('=',1) for x in shlex.split(prop('Environment')) if '=' in x)
 for f in re.findall(r'(\S+) \(ignore_errors=(?:yes|no)\)',prop('EnvironmentFiles')):
  for line in P(f).read_text().splitlines():
   line=line.strip()
   if not line or line.startswith('#') or '=' not in line:continue
   k,v=line.partition('=')[::2];k=k.strip().removeprefix('export ')
   if re.fullmatch('[A-Z_][A-Z0-9_]*',k):
    try:vals=shlex.split(v,comments=True);env[k]=vals[0] if vals else ''
    except ValueError:raise RuntimeError('ENV_PARSE_FAILED')
 return env

def sha(path):return hashlib.sha256(P(path).read_bytes()).hexdigest()
def mkdir(path):path.mkdir(parents=True,exist_ok=True);os.chown(path,pwd.getpwnam('Rizanrizan').pw_uid,pwd.getpwnam('Rizanrizan').pw_gid);path.chmod(0o700)

async def verify(token,url,probe_lease):
 from websockets.asyncio.client import connect
 async with connect(url,max_size=16_000_000,open_timeout=15) as ws:
  await ws.send(json.dumps(dict(type='hello',key=f'RZBTC7D130:{ACCOUNT}:BTCUSD',lease=probe_lease,contract='RZ-7D130-BTC8500283-LFOLLOW-WEEKEND',token=token)))
  ready=json.loads(await asyncio.wait_for(ws.recv(),15));assert ready['type']=='ready','BTC_HELLO_FAILED'
  feed=json.loads(await asyncio.wait_for(ws.recv(),20));assert feed['type']=='feed','BTC_FEED_NOT_READY'
  assert feed['through']==int(time.time())//3600*3600 and feed['contract']=='RZ-7D130-BTC8500283-LFOLLOW-WEEKEND','BTC_FEED_CONTRACT'
  assert len(feed['bars'])>=68280 and feed['bars'][-1][0]+3600==feed['through'],'BTC_FEED_COVERAGE'
  await ws.send('{"type":"ping"}');assert json.loads(await asyncio.wait_for(ws.recv(),10))['type']=='pong','BTC_PING_FAILED'
  return {'ready':True,'feed_current':True,'feed_rows':len(feed['bars']),'feed_through':feed['through'],'checkpoint_revision':ready['revision'],'recovered_state_present':ready['state'] is not None,'probe_checkpoint_writes':0}

def main():
 a=argparse.ArgumentParser();a.add_argument('--bundle',required=True);a.add_argument('--sha',required=True);a=a.parse_args()
 assert os.geteuid()==0 and re.fullmatch('[a-f0-9]{40}',a.sha),'INSTALL_CONTEXT'
 incoming=P(a.bundle).resolve();assert incoming.parent==HOME and incoming.name.startswith('btc7d-incoming-'),'BUNDLE_PATH'
 assert prop('ActiveState')=='active','MAIN_BRIDGE_NOT_ACTIVE'
 main_pid=prop('MainPID');source_hash=sha(MAIN/'cbot_bridge/server.py');env=environment()
 token=env.get('RIZAN_BRIDGE_TOKEN','');assert re.fullmatch(r'[A-Za-z0-9_-]{32,256}',token),'TOKEN_FORMAT_NOT_SUPPORTED'
 db=P(env.get('RIZAN_STATE_DB','state/rizan-checkpoints.sqlite'));db=db if db.is_absolute() else MAIN/db
 con=sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
 keys=[r[0] for r in con.execute('SELECT key FROM checkpoints')];con.close()
 assert any(f':{ACCOUNT}:' in k for k in keys),'ACCOUNT_NOT_OBSERVED_IN_MAIN_CHECKPOINTS'
 old_route=ROUTE.read_bytes();route=old_route.decode();assert 'location = /btc7d130' not in route and route.count('location / {')==1,'ROUTE_UNEXPECTED'
 assert not P('/etc/systemd/system/'+UNIT).exists(),'BTC_UNIT_ALREADY_EXISTS'
 mkdir(ROOT);mkdir(ROOT/'state');mkdir(ROOT/'releases');mkdir(ROOT/'backups')
 release=ROOT/'releases'/a.sha;mkdir(release)
 for name in ['server.py','store_base.py','timestamps.py','BITSTAMP_H1_SEED.csv','requirements.txt']:
  src=incoming/name;assert src.is_file(),'BUNDLE_INCOMPLETE';shutil.copyfile(src,release/name);(release/name).chmod(0o644)
 assert sha(release/'BITSTAMP_H1_SEED.csv')=='b8cc6dece79c77a2ad92c85f32cb37f45f5c003cc91910fe442c350fe7def4f4','SEED_CHECKSUM'
 venv=ROOT/'venv'
 if not (venv/'bin/python').exists():cmd(['runuser','-u','Rizanrizan','--','/usr/bin/python3','-m','venv',str(venv)],timeout=120)
 python=str(venv/'bin/python');cmd(['runuser','-u','Rizanrizan','--',python,'-m','pip','install','--disable-pip-version-check','-r',str(release/'requirements.txt')],timeout=180)
 # Check public feed catch-up BEFORE routing/service changes. No stale substitution.
 preflight="import sys,time,json;sys.path.insert(0,sys.argv[1]);from server import Feed;f=Feed(sys.argv[1]+'/BITSTAMP_H1_SEED.csv');f.update(time.time());w=json.loads(f.wire(time.time()));print(json.dumps({'feed_rows':len(w['bars']),'through':w['through']}))"
 pre=json.loads(cmd([python,'-c',preflight,str(release)],timeout=240))
 envpath=ROOT/'bridge.env';assert not envpath.exists(),'BTC_ENV_ALREADY_EXISTS'
 envpath.write_text(f'RZ7D_ACCOUNT={ACCOUNT}\nRZ7D_TOKEN={token}\nRZ7D_STATE_DB={ROOT}/state/btc7d130-research.sqlite\nRZ7D_SEED_CSV={release}/BITSTAMP_H1_SEED.csv\nRZ7D_LOOPBACK_PORT=8130\n');envpath.chmod(0o600)
 unitpath=P('/etc/systemd/system/'+UNIT)
 unit=f'''[Unit]
Description=RIZAN BTC 7D data and checkpoint bridge
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=Rizanrizan
Group={grp.getgrgid(pwd.getpwnam('Rizanrizan').pw_gid).gr_name}
WorkingDirectory={release}
EnvironmentFile={envpath}
ExecStart={python} {release}/server.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={ROOT}/state
[Install]
WantedBy=multi-user.target
'''
 addition='''location = /btc7d130 {
        proxy_pass http://127.0.0.1:8130;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 90s;
        proxy_send_timeout 90s;
        proxy_buffering off;
    }
    '''
 backup=ROOT/'backups'/('nginx-'+a.sha+'.conf');backup.write_bytes(old_route);backup.chmod(0o600)
 changed=False
 try:
  unitpath.write_text(unit);cmd(['systemctl','daemon-reload']);cmd(['systemctl','enable','--now',UNIT])
  # Feed warmup stays entry-blocked. Poll with isolated backend; original bridge unchanged.
  sys.path.insert(0,str(venv/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'))
  lease=os.urandom(16).hex();result=None
  for attempt in range(24):
   try:result=asyncio.run(verify(token,'ws://127.0.0.1:8130',lease));break
   except Exception:time.sleep(5)
  assert result is not None,'BTC_BACKEND_VALIDATION_FAILED'
  ROUTE.write_text(route.replace('location / {',addition+'location / {',1));changed=True
  cmd(['nginx','-t']);cmd(['systemctl','reload','nginx'])
  result=asyncio.run(verify(token,'wss://rizan-bridge.duckdns.org:25345/btc7d130',lease))
  assert prop('MainPID')==main_pid and sha(MAIN/'cbot_bridge/server.py')==source_hash,'MAIN_BRIDGE_CHANGED'
  assert prop('ActiveState')=='active','MAIN_BRIDGE_UNHEALTHY'
  result.update({'installed':True,'token_reused_from_main':True,'production_env_modified':False,'main_bridge_restarted':False,'main_pid_unchanged':True,'main_source_unchanged':True,'strategy_modified':False,'orders_sent':False,'cbot_trading_setting_changed':False,'btc_service':UNIT,'btc_url':'wss://rizan-bridge.duckdns.org:25345/btc7d130','preflight':pre,'probe_lease_expiry_seconds':45,'source_commit':a.sha})
  (ROOT/'DEPLOYMENT_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
 except Exception:
  if changed:ROUTE.write_bytes(old_route);cmd(['nginx','-t']);cmd(['systemctl','reload','nginx'])
  subprocess.run(['systemctl','disable','--now',UNIT],capture_output=True)
  # Retain backups, state and failed release for audit; no dataset deletion.
  raise
if __name__=='__main__':
 try:main()
 except Exception as e:print(json.dumps({'installed_and_verified':False,'failure_type':type(e).__name__,'reason':str(e) if isinstance(e,(AssertionError,RuntimeError)) else 'REDACTED','no_orders_sent':True}));sys.exit(1)

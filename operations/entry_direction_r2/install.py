"""Install an isolated market-only R2 snapshot worker. Trading bridge never restarted."""
import json,os,re,shutil,subprocess,sys
from pathlib import Path
APP=Path('/opt/rizan-entry-r2');OUT=Path('/var/lib/rizan-entry-r2');BASE=Path('/opt/rizan-bootstrap125-monitor/.venv/bin/python');PY=APP/'.venv/bin/python'
SNIPPET=Path('/etc/nginx/snippets/rizan-bootstrap125-locations.conf');BRIDGE='rizan-bootstrap125-bridge.service'
BLOCK='''
# RIZAN_ENTRY_R2_BEGIN
location = /bootstrap125/entry-direction-r2.json {
    alias /var/lib/rizan-entry-r2/snapshot.json;
    default_type application/json;
    etag off;
    if_modified_since off;
    add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    access_log off;
}
# RIZAN_ENTRY_R2_END
'''
UNIT='''[Unit]
Description=Independent R2 manual-entry market reader
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
WorkingDirectory=/opt/rizan-entry-r2
Environment=PYTHONPATH=/opt/rizan-entry-r2/src
Environment=OMP_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
ExecStart=/opt/rizan-entry-r2/.venv/bin/python /opt/rizan-entry-r2/scripts/collect_entry_direction_r2.py /var/lib/rizan-entry-r2
TimeoutStartSec=600
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/rizan-entry-r2
MemoryMax=768M
CPUQuota=30%
UMask=0077
'''
TIMER='''[Unit]
Description=Refresh independent R2 entry observation
[Timer]
OnBootSec=5
OnUnitInactiveSec=20
AccuracySec=1
[Install]
WantedBy=timers.target
'''

def run(args,timeout=600):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if p.returncode:
  for line in p.stdout.splitlines():
   if line.startswith('ENTRY_R2_'):print(line,flush=True)
  raise RuntimeError('R2_COMMAND_FAILED:'+Path(str(args[0])).name)
 return p

def identity():return run(['systemctl','show',BRIDGE,'-p','MainPID','-p','ExecMainStartTimestampMonotonic']).stdout

def main(source):
 if os.geteuid()!=0 or not BASE.exists() or not Path('/etc/rizan-bootstrap125-monitor-broker.json').exists():raise RuntimeError('READONLY_RUNTIME_REQUIRED')
 before=identity();APP.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True,mode=0o755)
 for name in ['__init__.py','models.py','exceptions.py','execution/ctrader_session.py','execution/ctrader_market_readonly.py']:
  target=APP/'src/fx_scanner'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/'src/fx_scanner'/name,target)
 (APP/'src/fx_scanner/execution/__init__.py').write_text('')
 shutil.copytree(source/'src/fx_scanner/entry_direction_r2',APP/'src/fx_scanner/entry_direction_r2',dirs_exist_ok=True)
 (APP/'scripts').mkdir(exist_ok=True);shutil.copyfile(source/'scripts/collect_entry_direction_r2.py',APP/'scripts/collect_entry_direction_r2.py')
 shutil.copyfile(source/'operations/entry_direction_r2/requirements.txt',APP/'requirements.txt')
 if not PY.exists():run([str(BASE),'-m','venv',str(APP/'.venv')])
 run([str(PY),'-m','pip','install','--disable-pip-version-check','-r',str(APP/'requirements.txt')])
 run([str(PY),str(APP/'scripts/collect_entry_direction_r2.py'),str(OUT)],timeout=600)
 p=json.loads((OUT/'snapshot.json').read_text())
 if p.get('contract')!='RIZAN_ENTRY_DIRECTION_R2_V1' or p.get('execution_authority') is not False:raise RuntimeError('R2_PREFLIGHT_CONTRACT')
 original=SNIPPET.read_text()
 if 'location ^~ /bootstrap125/' not in original:raise RuntimeError('R2_EXPECTED_ROUTE_MISSING')
 clean=re.sub(r'\n?# RIZAN_ENTRY_R2_BEGIN.*?# RIZAN_ENTRY_R2_END\n?','\n',original,flags=re.S)
 backup=Path('/var/backups/rizan-entry-r2');backup.mkdir(exist_ok=True,mode=0o700);(backup/'nginx-before.conf').write_text(original)
 try:
  SNIPPET.write_text(clean.rstrip()+'\n'+BLOCK);run(['nginx','-t']);Path('/etc/systemd/system/rizan-entry-r2.service').write_text(UNIT);Path('/etc/systemd/system/rizan-entry-r2.timer').write_text(TIMER)
  run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','rizan-entry-r2.timer']);run(['systemctl','reload','nginx']);run(['systemctl','is-active','--quiet','rizan-entry-r2.timer'])
 except Exception:
  SNIPPET.write_text(original);subprocess.run(['nginx','-t'],capture_output=True);subprocess.run(['systemctl','reload','nginx'],capture_output=True);raise
 if identity()!=before:raise RuntimeError('TRADING_BRIDGE_IDENTITY_CHANGED')
 print(json.dumps({'entry_r2_installed':True,'snapshot_status':p['status'],'trading_bridge_identity_unchanged':True,'execution_authority':False}),flush=True)

if __name__=='__main__':
 try:main(Path(sys.argv[1]))
 except Exception as exc:print('ENTRY_R2_INSTALL_FAILED:'+str(exc),flush=True);raise SystemExit(1)

"""Install only the independent manual R3 data timer and public static routes."""
import json,os,re,shutil,subprocess,sys
from pathlib import Path
APP=Path('/opt/rizan-manual-r3');OUT=Path('/var/lib/rizan-manual-r3')
SNIPPET=Path('/etc/nginx/snippets/rizan-bootstrap125-locations.conf')
BRIDGE='rizan-bootstrap125-bridge.service';PYTHON=Path('/opt/rizan-bootstrap125-monitor/.venv/bin/python')
SERVICE='rizan-manual-r3.service';TIMER='rizan-manual-r3.timer'
BLOCK='''
# RIZAN_MANUAL_R3_BEGIN
location = /bootstrap125/manual-r3.json {
    alias /var/lib/rizan-manual-r3/market.json;
    default_type application/json;
    etag off;
    if_modified_since off;
    add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    access_log off;
}
location = /bootstrap125/manual-r3-news.json {
    alias /var/lib/rizan-manual-r3/news.json;
    default_type application/json;
    etag off;
    if_modified_since off;
    add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    access_log off;
}
# RIZAN_MANUAL_R3_END
'''
UNIT='''[Unit]
Description=Independent manual R3 market-data reader
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
WorkingDirectory=/opt/rizan-manual-r3
Environment=PYTHONPATH=/opt/rizan-manual-r3/src
ExecStart=/opt/rizan-bootstrap125-monitor/.venv/bin/python /opt/rizan-manual-r3/publish.py
TimeoutStartSec=180
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/rizan-manual-r3
UMask=0077
MemoryMax=256M
CPUQuota=25%
'''
TIMER_UNIT='''[Unit]
Description=Refresh the independent manual R3 feed
[Timer]
OnBootSec=3
OnUnitInactiveSec=10
AccuracySec=1
[Install]
WantedBy=timers.target
'''

def run(args,timeout=200):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        for line in result.stdout.splitlines():
            if line.startswith(('R3_COLLECTION_FAILED:','MANUAL_R3_PUBLISH_FAILED:')):print(line,flush=True)
        print('R3_INSTALL_COMMAND_FAILED:'+Path(args[0]).name,flush=True)
        result.check_returncode()
    return result
def bridge_identity():return run(['systemctl','show',BRIDGE,'-p','MainPID','-p','ExecMainStartTimestampMonotonic']).stdout
def stop_previous_reader():
    for unit in [TIMER,SERVICE]:
        loaded=run(['systemctl','show',unit,'-p','LoadState','--value']).stdout.strip()
        if loaded!='not-found':run(['systemctl','stop',unit])
def main(source):
    if os.geteuid()!=0 or not PYTHON.exists():raise RuntimeError('EXISTING_READONLY_RUNTIME_REQUIRED')
    if not Path('/etc/rizan-bootstrap125-monitor-broker.json').exists():raise RuntimeError('READONLY_CREDENTIALS_MISSING')
    before=bridge_identity();stop_previous_reader();original=SNIPPET.read_text()
    if 'location ^~ /bootstrap125/' not in original:raise RuntimeError('EXPECTED_ROUTE_MISSING')
    APP.mkdir(exist_ok=True,mode=0o755);OUT.mkdir(exist_ok=True,mode=0o755)
    for n in ['__init__.py','models.py','exceptions.py','manual_r3_feed.py','execution/ctrader_session.py','execution/ctrader_market_readonly.py']:
        target=APP/'src/fx_scanner'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/'src/fx_scanner'/n,target)
    (APP/'src/fx_scanner/execution/__init__.py').write_text('')
    (APP/'scripts').mkdir(exist_ok=True);shutil.copyfile(source/'scripts/collect_manual_r3.py',APP/'scripts/collect_manual_r3.py')
    shutil.copyfile(source/'operations/manual_r3/publish.py',APP/'publish.py')
    run([str(PYTHON),str(APP/'publish.py')],timeout=175)
    clean=re.sub(r'\n?# RIZAN_MANUAL_R3_BEGIN.*?# RIZAN_MANUAL_R3_END\n?','\n',original,flags=re.S)
    backup=Path('/var/backups/rizan-manual-r3');backup.mkdir(exist_ok=True,mode=0o700);(backup/'nginx-before.conf').write_text(original)
    try:
        SNIPPET.write_text(clean.rstrip()+'\n'+BLOCK);run(['nginx','-t'])
        Path('/etc/systemd/system',SERVICE).write_text(UNIT);Path('/etc/systemd/system',TIMER).write_text(TIMER_UNIT)
        run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',TIMER]);run(['systemctl','reload','nginx'])
        run(['systemctl','start',SERVICE]);run(['systemctl','is-active','--quiet',TIMER])
    except Exception:
        SNIPPET.write_text(original);subprocess.run(['nginx','-t'],capture_output=True);subprocess.run(['systemctl','reload','nginx'],capture_output=True);raise
    if bridge_identity()!=before:raise RuntimeError('TRADING_BRIDGE_IDENTITY_CHANGED')
    print(json.dumps({'installed':True,'manual_timer_seconds':10,'trading_service_not_restarted':True}))
if __name__=='__main__':
    try:main(Path(sys.argv[1]))
    except Exception as e:print('R3_INSTALL_FAILED:'+type(e).__name__);raise SystemExit(1)

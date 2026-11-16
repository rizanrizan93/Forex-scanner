"""Install independent read-only status timers, preserving the trading service."""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

APP=Path('/opt/rizan-bootstrap125-monitor')
OUT=Path('/var/lib/rizan-bootstrap125-monitor')
SNIPPET=Path('/etc/nginx/snippets/rizan-bootstrap125-locations.conf')
BRIDGE='rizan-bootstrap125-bridge.service'
MARKER='# RIZAN_V1_MONITOR_STATIC_BEGIN'
BLOCK='''
# RIZAN_V1_MONITOR_STATIC_BEGIN
location = /bootstrap125/status.json {
    alias /var/lib/rizan-bootstrap125-monitor/status.json;
    default_type application/json;
    add_header Cache-Control "no-store, max-age=0" always;
    access_log off;
}
location = /bootstrap125/broker.json {
    alias /var/lib/rizan-bootstrap125-monitor/broker.json;
    default_type application/json;
    add_header Cache-Control "no-store, max-age=0" always;
    access_log off;
}
location = /bootstrap125/market.json {
    alias /var/lib/rizan-bootstrap125-monitor/market.json;
    default_type application/json;
    add_header Cache-Control "no-store, max-age=0" always;
    access_log off;
}
# RIZAN_V1_MONITOR_STATIC_END
'''

def run(args):
    return subprocess.run(args,check=True,text=True,capture_output=True,timeout=150)

def bridge_identity():
    return run(['systemctl','show',BRIDGE,'-p','MainPID','-p','ExecMainStartTimestampMonotonic']).stdout

def main():
    if os.geteuid()!=0: raise RuntimeError('ROOT_REQUIRED')
    run(['systemctl','is-active','--quiet',BRIDGE])
    before=bridge_identity()
    original=SNIPPET.read_text()
    if 'location ^~ /bootstrap125/' not in original: raise RuntimeError('EXPECTED_V1_ROUTE_MISSING')
    source=Path(sys.argv[1])
    APP.mkdir(exist_ok=True,mode=0o755)
    OUT.mkdir(exist_ok=True,mode=0o755)
    for name in ['read_bootstrap125_dashboard.py','publish_bootstrap125_status.py','read_bootstrap125_broker.py']:
        shutil.copyfile(source/'scripts'/name,APP/name)
        (APP/name).chmod(0o644)
    for name in ['__init__.py','models.py','exceptions.py','execution/ctrader_session.py']:
        target=APP/'src/fx_scanner'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/'src/fx_scanner'/name,target)
    (APP/'src/fx_scanner/execution/__init__.py').write_text('')
    venv=APP/'.venv'
    if not (venv/'bin/python').exists(): run(['python3','-m','venv',str(venv)])
    run([str(venv/'bin/pip'),'install','--disable-pip-version-check','ctrader-open-api==0.9.2','service-identity==24.2.0'])
    common='''NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/rizan-bootstrap125-monitor
UMask=0077
'''
    units={
        'rizan-bootstrap125-status.service':'''[Unit]
Description=Read-only Bootstrap125 checkpoint publication
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/rizan-bootstrap125-monitor/publish_bootstrap125_status.py
TimeoutStartSec=15
'''+common,
        'rizan-bootstrap125-status.timer':'''[Unit]
Description=Refresh sanitized Bootstrap125 status
[Timer]
OnBootSec=5
OnUnitActiveSec=10
AccuracySec=1
[Install]
WantedBy=timers.target
''',
        'rizan-bootstrap125-broker.service':'''[Unit]
Description=Read-only Bootstrap125 broker history and market evidence
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
Environment=PYTHONPATH=/opt/rizan-bootstrap125-monitor/src
ExecStart=/opt/rizan-bootstrap125-monitor/.venv/bin/python /opt/rizan-bootstrap125-monitor/read_bootstrap125_broker.py
TimeoutStartSec=140
'''+common,
        'rizan-bootstrap125-broker.timer':'''[Unit]
Description=Refresh read-only Bootstrap125 broker evidence
[Timer]
OnBootSec=15
OnUnitActiveSec=60
AccuracySec=2
[Install]
WantedBy=timers.target
'''}
    for name, content in units.items(): Path('/etc/systemd/system',name).write_text(content)
    secret=source/'broker-credentials.json'
    target=Path('/etc/rizan-bootstrap125-monitor-broker.json')
    if secret.exists():
        target.write_bytes(secret.read_bytes());target.chmod(0o600)
    if not target.exists(): raise RuntimeError('BROKER_CREDENTIALS_UNAVAILABLE')
    clean=re.sub(r'\n?# RIZAN_V1_MONITOR_STATIC_BEGIN.*?# RIZAN_V1_MONITOR_STATIC_END\n?', '\n', original, flags=re.S)
    if MARKER not in original:
        backup=Path('/var/backups/rizan-bootstrap125-monitor')
        backup.mkdir(exist_ok=True,mode=0o700)
        (backup/('nginx-'+str(int(time.time()))+'.conf')).write_text(original)
    try:
        SNIPPET.write_text(clean.rstrip()+'\n'+BLOCK)
        run(['nginx','-t'])
        run(['systemctl','daemon-reload'])
        run(['systemctl','start','rizan-bootstrap125-status.service'])
        run(['systemctl','enable','--now','rizan-bootstrap125-status.timer','rizan-bootstrap125-broker.timer'])
        run(['systemctl','reload','nginx'])
        run(['systemctl','start','rizan-bootstrap125-broker.service'])
    except Exception:
        SNIPPET.write_text(original)
        subprocess.run(['nginx','-t'],capture_output=True)
        subprocess.run(['systemctl','reload','nginx'],capture_output=True)
        raise
    if before!=bridge_identity(): raise RuntimeError('TRADING_SERVICE_IDENTITY_CHANGED')
    print(json.dumps(dict(installed=True,trading_service_not_restarted=True,
                         observed_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())))

if __name__=='__main__':
    try: main()
    except Exception as e:
        print('MONITOR_INSTALL_FAILED:'+type(e).__name__,flush=True)
        raise SystemExit(1)

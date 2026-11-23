"""Install observer only; no broker/API calls or modifications to trading units."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BRIDGE='rizan-bootstrap125-bridge.service'
APP=Path('/opt/rizan-bootstrap125-watchdog')
SERVICE='''[Unit]
Description=RIZAN V1 independent read-only heartbeat observer
[Service]
Type=oneshot
DynamicUser=yes
ExecStart=/usr/bin/python3 /opt/rizan-bootstrap125-watchdog/watchdog.py
TimeoutStartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
InaccessiblePaths=-/var/lib/rizan-bootstrap125-bridge -/etc/rizan-bootstrap125-bridge.env -/etc/rizan-bootstrap125-monitor-broker.json
'''
TIMER='''[Unit]
Description=Check V1 role lease freshness every ten seconds
[Timer]
OnBootSec=5
OnUnitActiveSec=10
AccuracySec=1
[Install]
WantedBy=timers.target
'''

def run(args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30).stdout

def identity():return run(['systemctl','show',BRIDGE,'-p','MainPID','-p','ExecMainStartTimestampMonotonic'])

def main():
    if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
    before=identity()
    source=Path(sys.argv[1]);APP.mkdir(mode=0o755,exist_ok=True)
    for name in ('watchdog.py','cbot_v1_reliability.py'):
        with tempfile.NamedTemporaryFile(dir=APP,delete=False) as f:
            f.write((source/name).read_bytes());f.flush();os.fsync(f.fileno())
        os.chmod(f.name,0o644);os.replace(f.name,APP/name)
    for name,text in (('service',SERVICE),('timer',TIMER)):
        Path('/etc/systemd/system/rizan-bootstrap125-watchdog.'+name).write_text(text)
    run(['systemctl','daemon-reload'])
    run(['systemctl','start','rizan-bootstrap125-watchdog.service'])
    run(['systemctl','enable','--now','rizan-bootstrap125-watchdog.timer'])
    if before!=identity():raise RuntimeError('TRADING_SERVICE_IDENTITY_CHANGED')
    print(json.dumps(dict(installed=True,trading_service_identity_unchanged=True,automatic_recovery=False)))

if __name__=='__main__':main()

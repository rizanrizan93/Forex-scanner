"""Install an independent candle timer and static route without bridge restart."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

APP = Path('/opt/rizan-xau-candles')
OUT = Path('/var/lib/rizan-xau-candles')
SNIPPET = Path('/etc/nginx/snippets/rizan-bootstrap125-locations.conf')
BRIDGE = 'rizan-bootstrap125-bridge.service'
PYTHON = Path('/opt/rizan-bootstrap125-monitor/.venv/bin/python')
SERVICE = 'rizan-xau-candles.service'
TIMER = 'rizan-xau-candles.timer'
BLOCK = '''
# RIZAN_XAU_CANDLES_BEGIN
location = /bootstrap125/xau-candles.json {
    alias /var/lib/rizan-xau-candles/candles.json;
    default_type application/json;
    etag off;
    if_modified_since off;
    add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    access_log off;
}
# RIZAN_XAU_CANDLES_END
'''
UNIT = '''[Unit]
Description=Independent read-only XAU closed candle collector
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
WorkingDirectory=/opt/rizan-xau-candles
Environment=PYTHONPATH=/opt/rizan-xau-candles/src
ExecStart=/opt/rizan-bootstrap125-monitor/.venv/bin/python /opt/rizan-xau-candles/publish.py
TimeoutStartSec=95
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/rizan-xau-candles
UMask=0077
MemoryMax=256M
CPUQuota=25%
'''
TIMER_UNIT = '''[Unit]
Description=Refresh XAU candles independently of GitHub Actions and browser sessions
[Timer]
OnBootSec=5
OnUnitActiveSec=20
AccuracySec=1
[Install]
WantedBy=timers.target
'''


def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=110)


def bridge_identity():
    return run(['systemctl','show',BRIDGE,'-p','MainPID','-p','ExecMainStartTimestampMonotonic']).stdout


def main(source):
    if os.geteuid() != 0:
        raise RuntimeError('ROOT_REQUIRED')
    if not PYTHON.exists() or not Path('/etc/rizan-bootstrap125-monitor-broker.json').exists():
        raise RuntimeError('EXISTING_READONLY_RUNTIME_MISSING')
    run(['systemctl','is-active','--quiet',BRIDGE])
    before = bridge_identity()
    original = SNIPPET.read_text()
    if 'location ^~ /bootstrap125/' not in original:
        raise RuntimeError('EXPECTED_ROUTE_MISSING')
    APP.mkdir(exist_ok=True, mode=0o755)
    OUT.mkdir(exist_ok=True, mode=0o755)
    for name in ['__init__.py','models.py','exceptions.py','xau_decision_checklist_v1.py',
                 'xau_decision_candle_feed_v1.py','execution/ctrader_session.py',
                 'execution/ctrader_market_readonly.py']:
        target = APP/'src/fx_scanner'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/'src/fx_scanner'/name, target)
    (APP/'src/fx_scanner/execution/__init__.py').write_text('')
    (APP/'scripts').mkdir(exist_ok=True)
    shutil.copyfile(source/'scripts/collect_xau_decision_readonly.py', APP/'scripts/collect_xau_decision_readonly.py')
    shutil.copyfile(source/'operations/xau_candles/publish.py', APP/'publish.py')
    # Preflight a real collection before changing routing or enabling timers.
    env = dict(os.environ, PYTHONPATH=str(APP/'src'))
    subprocess.run([str(PYTHON),str(APP/'publish.py')], env=env, check=True, timeout=90)
    clean = re.sub(r'\n?# RIZAN_XAU_CANDLES_BEGIN.*?# RIZAN_XAU_CANDLES_END\n?', '\n', original, flags=re.S)
    backup = Path('/var/backups/rizan-xau-candles')
    backup.mkdir(exist_ok=True, mode=0o700)
    (backup/'nginx-before.conf').write_text(original)
    try:
        SNIPPET.write_text(clean.rstrip()+'\n'+BLOCK)
        run(['nginx','-t'])
        Path('/etc/systemd/system', SERVICE).write_text(UNIT)
        Path('/etc/systemd/system', TIMER).write_text(TIMER_UNIT)
        run(['systemctl','daemon-reload'])
        run(['systemctl','enable','--now',TIMER])
        run(['systemctl','reload','nginx'])
        run(['systemctl','start',SERVICE])
        run(['systemctl','is-active','--quiet',TIMER])
    except Exception:
        SNIPPET.write_text(original)
        subprocess.run(['nginx','-t'], capture_output=True)
        subprocess.run(['systemctl','reload','nginx'], capture_output=True)
        raise
    if bridge_identity() != before:
        raise RuntimeError('BRIDGE_IDENTITY_CHANGED')
    print(json.dumps({'installed': True, 'timer_seconds': 20,
                      'trading_service_not_restarted': True}))


if __name__ == '__main__':
    try:
        main(Path(sys.argv[1]))
    except Exception as exc:
        print('XAU_CANDLE_INSTALL_FAILED:'+type(exc).__name__, flush=True)
        raise SystemExit(1)

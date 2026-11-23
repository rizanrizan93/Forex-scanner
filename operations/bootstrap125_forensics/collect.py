"""Non-interfering evidence collector. Raw logs stay root-private on VPS.
No broker calls, service mutations, checkpoint writes or process signalling.
"""
import gzip
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

START = '2026-11-17 00:00:00 UTC'
END = '2026-11-24 00:00:00 UTC'
PATTERNS = {
    'OOM': r'out of memory|oom-kill|killed process|oom_reaper',
    'SERVICE_STOP': r'Stopping |Stopped |Deactivated successfully|Main process exited',
    'SERVICE_START': r'Starting |Started |Scheduled restart job',
    'PROCESS_FAILURE': r'Failed with result|segfault|core dump|watchdog timeout',
    'WS_DISCONNECT': r'connection closed|connection reset|disconnected|keepalive ping timeout|opening handshake failed',
    'LEASE_ERROR': r'LEASE_BUSY|LEASE_EXPIRED',
    'AUTH_ERROR': r'AUTH_FAILED|ACCOUNT_NOT_ALLOWED|authentication failed|session expired',
    'BOT_FAULT': r'RIZAN_UNHANDLED_EXCEPTION|R3_PORTFOLIO_TIMER_BLOCK|BRIDGE_SAFETY_FAULT|PORTFOLIO_ENGINE_STOP_ERROR',
    'BOT_OFFLINE': r'BOOTSTRAP_BRIDGE_OFFLINE|BRIDGE_OFFLINE',
    'BOT_HEALTH': r'RIZAN_RUNTIME_HEALTH|RIZAN_PORTFOLIO',
    'HOST_SHUTDOWN': r'Shutting down|Rebooting|Linux version|systemd-shutdown',
}

def capture(args):
    try:
        p = subprocess.run(args, capture_output=True, timeout=90)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, b'', type(exc).__name__.encode()


def main():
    if os.geteuid() != 0:
        raise RuntimeError('ROOT_REQUIRED')
    os.umask(0o077)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = Path('/var/lib/rizan-bootstrap125-forensics') / stamp
    folder.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = dict(observed_at=datetime.now(timezone.utc).isoformat(), read_only=True,
                  execution_authority=False, evidence_directory=str(folder),
                  interval_utc=[START, END], journals={}, errors=[])
    manifest = {}
    for name, args in {
        'bridge': ['journalctl', '-u', 'rizan-bootstrap125-bridge.service'],
        'system': ['journalctl', '-p', 'warning'],
        'kernel': ['journalctl', '-k'],
        'nginx': ['journalctl', '-u', 'nginx.service'],
        'incident_all': ['journalctl'],
    }.items():
        since, until = ('2026-11-18 00:45:00 UTC','2026-11-18 02:00:00 UTC') if name=='incident_all' else (START,END)
        code, raw, err = capture(args + ['--since', since, '--until', until, '--utc', '-o', 'json', '--no-pager', '-n', '20000'])
        (folder / (name+'.journal.jsonl')).write_bytes(raw)
        manifest[name] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), returncode=code)
        events, counts, first, last, total = [], Counter(), None, None, 0
        units=Counter(); matches=Counter()
        for line in raw.splitlines():
            try:
                row=json.loads(line); us=int(row['__REALTIME_TIMESTAMP'])
                at=datetime.fromtimestamp(us/1e6,timezone.utc).isoformat()
                msg=str(row.get('MESSAGE','')); total+=1
                first=min(first or at, at); last=max(last or at, at)
                for category, pattern in PATTERNS.items():
                    if re.search(pattern,msg,re.I):
                        counts[category]+=1
                        unit=str(row.get('_SYSTEMD_UNIT',row.get('SYSLOG_IDENTIFIER','UNKNOWN')))
                        if re.fullmatch(r'[A-Za-z0-9_.@:-]{1,100}',unit): units[(category,unit)]+=1
                        match=re.search(pattern,msg,re.I).group(0)
                        matches[(category,match)]+=1
                        if len(events)<1500:
                            events.append(dict(at=at,event=category,message_sha256=hashlib.sha256(msg.encode()).hexdigest()))
            except (KeyError, ValueError, TypeError):
                continue
        report['journals'][name]=dict(**manifest[name], rows=total, capped=total>=20000,
                                     first_at=first,last_at=last,counts=dict(counts),events=events,
                                     unit_counts=[dict(event=c,unit=u,count=n) for (c,u),n in units.items()],
                                     matched_phrases=[dict(event=c,phrase=p,count=n) for (c,p),n in matches.items()])
    code,raw,err=capture(['journalctl','--list-boots','--no-pager'])
    (folder/'boots.txt').write_bytes(raw)
    report['boot_history']=raw.decode(errors='replace').splitlines()[-15:]
    fields=['ActiveState','SubState','MainPID','NRestarts','Result','ExecMainCode','ExecMainStatus',
            'ActiveEnterTimestamp','ExecMainStartTimestamp','ExecMainExitTimestamp']
    code,raw,err=capture(['systemctl','show','rizan-bootstrap125-bridge.service'] + ['--property='+x for x in fields])
    report['service']=dict(line.split('=',1) for line in raw.decode().splitlines() if '=' in line)
    report['sources']=[]
    for root in [Path('/opt/rizan-bootstrap125-bridge'),Path('/etc/systemd/system')]:
        candidates = root.rglob('*.py') if root.name!='system' else root.glob('rizan-bootstrap125*.service')
        for p in candidates:
            if '.venv' in p.parts or '__pycache__' in p.parts: continue
            try:
                raw=p.read_bytes();report['sources'].append(dict(path=str(p),size=len(raw),mtime_utc=datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),sha256=hashlib.sha256(raw).hexdigest()))
            except OSError: pass
    # No full environment, command lines, labels, account IDs, lease tokens, or raw state leave VPS.
    code,raw,err=capture(['ps','-eo','comm='])
    report['ctrader_process_names']=[v for v in raw.decode().splitlines() if re.search(r'ctrader|calgo|dotnet',v,re.I)]
    try:
        script=Path('/opt/rizan-bootstrap125-monitor/read_bootstrap125_dashboard.py')
        spec=importlib.util.spec_from_file_location('v1_readonly',script);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        report['snapshot']=m.snapshot()
    except Exception as exc: report['errors'].append('SNAPSHOT_'+type(exc).__name__)
    dbpath=Path('/var/lib/rizan-bootstrap125-bridge/checkpoints.sqlite')
    try:
        db=sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        report['checkpoint_integrity']=db.execute('PRAGMA quick_check').fetchone()[0]
        report['checkpoint_counts']={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('checkpoints','bridge_leases','checkpoint_receipts')}
        db.close()
    except Exception as exc: report['errors'].append('SQLITE_'+type(exc).__name__)
    # Access logs are preserved privately; publish only role-route/time/status counts.
    report['http_access']={}
    report['nginx_log_files']=[dict(name=p.name,bytes=p.stat().st_size) for p in Path('/var/log/nginx').iterdir() if p.is_file()]
    for p in Path('/var/log/nginx').glob('*access.log*'):
        if not p.is_file(): continue
        try:
            rows=[]
            opener=gzip.open if p.suffix=='.gz' else open
            with opener(p,'rt',errors='replace') as f:
                for line in f:
                    if '/bootstrap125' in line and re.search(r'1[7-9]/Nov/2026|2[0-3]/Nov/2026',line): rows.append(line)
            raw=''.join(rows).encode();(folder/(p.name+'.private')).write_bytes(raw)
            counts=Counter()
            for line in rows:
                hit=re.search(r'\[([^]]+)\].*?"(?:GET|POST) (/bootstrap125[^ ?"]*)[^\"]*" (\d{3})',line)
                if hit: counts[(hit[1],hit[2],hit[3])]+=1
            report['http_access'][p.name]=dict(rows=len(rows),sha256=hashlib.sha256(raw).hexdigest(),events=[dict(at=a,route=b,status=c,count=n) for (a,b,c),n in counts.items()][:2000])
        except OSError: pass
    (folder/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    (folder/'summary.json').write_text(json.dumps(report,sort_keys=True))
    print(json.dumps(report,allow_nan=False))

if __name__=='__main__': main()

"""Update bridge transport only; preserve DB, leases, env, ports and other services."""
from pathlib import Path
import hashlib,subprocess,time,os,json,shutil
UNIT='rizan-btc10-bridge.service'
TARGET=Path('/opt/rizan-btc10-bridge/server.py')
def run(args):return subprocess.run(args,check=True,text=True,capture_output=True)
def prop(unit,name):return run(['systemctl','show',unit,'--value','-p',name]).stdout.strip()
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if os.geteuid()!=0:raise RuntimeError('ROOT_REQUIRED')
    source=Path('candidate/bridge/server.py').resolve()
    expected=Path('candidate/bridge/server.before.sha256').read_text().strip()
    if not TARGET.is_file() or TARGET.is_symlink() or digest(TARGET)!=expected:
        raise RuntimeError('LIVE_SOURCE_CHANGED_ABORT_NO_MUTATION')
    if prop(UNIT,'ActiveState')!='active':raise RuntimeError('SERVICE_NOT_ACTIVE_ABORT')
    others={u:prop(u,'ExecMainStartTimestampMonotonic') for u in ['nginx.service','rizan-cbot-bridge.service','rizan-btc7d130.service']}
    backup=Path('/var/backups/rizan-btc10-transport')/str(time.time_ns())
    backup.mkdir(parents=True,mode=0o700);shutil.copy2(TARGET,backup/'server.py')
    staged=TARGET.with_name('server.py.transport-new')
    shutil.copy2(TARGET,staged);staged.write_bytes(source.read_bytes())
    # Syntax check without importing server or accessing production data.
    compile(staged.read_text(),str(TARGET),'exec')
    os.replace(staged,TARGET)
    try:
        run(['systemctl','restart',UNIT])
        time.sleep(3)
        run(['systemctl','is-active','--quiet',UNIT])
        if digest(TARGET)!=digest(source):raise RuntimeError('SOURCE_HASH_MISMATCH')
        if any(prop(u,'ExecMainStartTimestampMonotonic')!=v for u,v in others.items()):
            raise RuntimeError('OTHER_SERVICE_CHANGED')
    except Exception:
        rollback=TARGET.with_name('server.py.transport-rollback');shutil.copy2(backup/'server.py',rollback);os.replace(rollback,TARGET)
        run(['systemctl','restart',UNIT]);raise
    print(json.dumps({'deployed':True,'transport_only':True,'service':UNIT,
        'server_sha256':digest(TARGET),'backup':str(backup),'broker_requests':0,
        'database_or_lease_writes':0,'other_services_unchanged':True,
        'observed_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}),flush=True)
if __name__=='__main__':main()

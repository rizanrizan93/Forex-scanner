"""Read-only BUY050 VPS prerequisites. Never emit credentials/account number."""
import json,re,socket,subprocess
from pathlib import Path
from provision_isolated import inherited,tls_server_close
def status(unit):
    r=subprocess.run(['systemctl','is-active',unit],text=True,capture_output=True)
    return r.stdout.strip()[:24] if r.returncode==0 else 'inactive'
def run():
    result={'check':'BUY050_VPS_PREFLIGHT','readonly':True,'account_suffix':'7903','old_services':{},'ready':False}
    for unit in ['rizan-cbot-bridge.service','rizan-compression-bridge.service','rizan-tp500-bridge.service','rizan-btc10-bridge.service','rizan-disp1506-bridge.service','rizan-buy050-bridge.service']:
        result['old_services'][unit]=status(unit)
    result['buy050_unit_absent']=not Path('/etc/systemd/system/rizan-buy050-bridge.service').exists()
    result['buy050_state_absent']=not Path('/var/lib/rizan-buy050-bridge').exists()
    result['buy050_env_absent']=not Path('/etc/rizan-buy050-bridge.env').exists()
    result['buy050_app_absent']=not Path('/opt/rizan-buy050-bridge').exists()
    try:
        env=inherited()
        token=env.get('R3_BRIDGE_TOKEN','')
        accounts=[s.strip() for s in env.get('R3_ALLOWED_ACCOUNTS','').split(',') if s.strip().isdigit() and s.strip().endswith('7903')]
        result['legacy_token_available']=len(token)>=32
        result['unique_account_binding']=len(accounts)==1
        cache=Path(env.get('R3_STATE_DIR','/var/lib/rizan-btc10-bridge'))/'btc-m1.sqlite'
        result['btc_cache_present']=cache.is_file() and cache.stat().st_size>0
    except Exception:
        result['legacy_env_readable']=False
    else:
        result['legacy_env_readable']=True
    try:
        with socket.socket() as s:s.bind(('127.0.0.1',25352))
        result['local_port_free']=True
    except OSError:
        result['local_port_free']=False
    try:
        nginx=subprocess.run(['nginx','-T'],text=True,capture_output=True,check=True).stdout
        entries=[]
        for m in re.finditer(r'^# configuration file ([^:]+):$',nginx,re.M):
            p=Path(m.group(1).strip())
            if p.is_file():
                v=p.read_text()
                if tls_server_close(v) is not None:entries.append(v)
        result['single_25345_vhost']=len(entries)==1
        result['buy050_route_absent']=all('/buy050' not in x for x in entries)
    except Exception:
        result['single_25345_vhost']=False
        result['buy050_route_absent']=False
    must=['buy050_unit_absent','buy050_state_absent','buy050_env_absent','buy050_app_absent','legacy_token_available','unique_account_binding','btc_cache_present','legacy_env_readable','local_port_free','single_25345_vhost','buy050_route_absent']
    result['ready']=all(result.get(x,False) for x in must)
    print(json.dumps(result,sort_keys=True))
    if not result['ready']:raise SystemExit(2)
if __name__=='__main__':run()

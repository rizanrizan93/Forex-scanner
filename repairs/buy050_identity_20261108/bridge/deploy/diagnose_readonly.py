"""BUY050 read-only post-install diagnostics; never log credentials or full accounts."""
import json,os,re,subprocess,sys,socket
from datetime import datetime,timezone
from pathlib import Path
def report():
    root=Path('/var/lib/rizan-buy050-bridge')
    record={'read_only':True,'unit':'rizan-buy050-bridge.service','account_suffix':'7903'}
    unit=subprocess.run(['systemctl','is-active','rizan-buy050-bridge.service'],text=True,capture_output=True)
    record['service_active']=unit.stdout.strip()=='active'
    record['binary_server_present']=Path('/opt/rizan-buy050-bridge/server.py').exists()
    p=root/'health.json'
    if p.is_file():
        try:
            data=json.loads(p.read_text())
            stamp=data.get('observed_utc')
            dt=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            record['health_age_seconds']=round((datetime.now(timezone.utc)-dt).total_seconds(),1)
            record['btc_state']=str(data.get('btc','ABSENT'))[:60]
            record['macro_snapshot_present']=data.get('macro_snapshot_present')
            record['connected']=data.get('connected')
        except Exception:
            record['health_read_error']=True
    else:record['health_file_present']=False
    try:
        with socket.create_connection(('127.0.0.1',25352),timeout=3):
            record['local_listener_open']=True
    except Exception:record['local_listener_open']=False
    values={}
    try:
        for line in Path('/etc/rizan-buy050-bridge.env').read_text().splitlines():
            k,sep,v=line.partition('=')
            if sep:values[k]=v.strip()
    except Exception:record['env_available']=False
    else:record['env_available']=True
    if record.get('env_available'):
        env=os.environ.copy()
        env.update(values,BUY050_PUBLIC_URL='wss://rizan-bridge.duckdns.org:25345/buy050',BUY050_PROBE_ACCOUNT=values.get('BUY050_ALLOWED_ACCOUNTS','').split(',')[0])
        try:
            response=subprocess.run(['/opt/rizan-buy050-bridge/.venv/bin/python','/opt/rizan-buy050-bridge/probe.py'],capture_output=True,text=True,timeout=55,env=env)
            raw=response.stderr[-3000:]+response.stdout[-2000:]
            patterns={'auth_failed':r'AUTH_FAILED','identity_invalid':r'IDENTITY_INVALID','path_invalid':r'PATH_INVALID','lease_busy':r'LEASE_BUSY','feed_unavailable':r'Feed not ready|feed_unavailable|data_ready.?false','timeout':r'TimeoutError|timed out|Timeout','tls_error':r'SSLError|CERTIFICATE_VERIFY_FAILED','http_status':r'InvalidStatus|HTTP 4[0-9][0-9]','connection_failed':r'ConnectionRefused|ConnectionClosed|ConnectionReset','dns_failed':r'gaierror|Name or service not known','handshake_not_ready':r'handshake failed','no_btc_feed':r'BTCUSD.*data_ready.?false','macro_stale':r'XAUUSD.*data_ready.?false'}
            record['probe_return_code']=response.returncode
            record['probe_flags']={k:bool(re.search(p,raw,re.I)) for k,p in patterns.items()}
            try:
                start=response.stdout.index('{')
                obj,_=json.JSONDecoder().raw_decode(response.stdout[start:])
                record['per_symbol']={k:{field:v.get(field) for field in ('handshake','heartbeat','data_ready','orders')} for k,v in obj.items() if k in ('XAUUSD','EURUSD','BTCUSD') and isinstance(v,dict)}
            except Exception:record['probe_result_parse_error']=True
            if response.returncode!=0 and not any(record['probe_flags'].values()):
                record['failure_kind']=next((c for c in ['ValueError','RuntimeError','OSError','SystemExit','KeyError','FileNotFoundError','PermissionError','TypeError'] if c in raw),'UNKNOWN')
        except subprocess.TimeoutExpired:record['probe_timed_out']=True
    print(json.dumps(record,sort_keys=True))
if __name__=='__main__':report()

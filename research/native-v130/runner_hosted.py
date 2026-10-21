"""VPS entry point for autonomous native M1 cBot lifecycle tests."""
import base64, hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

root=Path(sys.argv[1]).resolve()
os.umask(0o077)
if len(sys.argv)>2 and sys.argv[2]=='hosted':
    identity=json.loads((root/'AUTH_PRIVATE.json').read_text())
    docker=['docker']
    password=root/'password.pwd'
    (root/'AUTH_PRIVATE.json').unlink()
else:
    context=json.loads((Path.home()/'.local/state/rizan-native-preflight/context.json').read_text())
    docker=context['DockerPrefix']; assert docker and docker[-1].endswith('docker')
    passwords=context['CredentialCandidates']; assert len(passwords)==1
    password=Path(passwords[0]); assert password.is_file() and not password.is_symlink()
    identity=json.loads(subprocess.run(['openssl','pkeyutl','-decrypt','-inkey',
        str(Path.home()/'.local/state/rizan-native-preflight/transfer.pem'),
        '-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256',
        '-pkeyopt','rsa_mgf1_md:sha256'],
        input=base64.b64decode((root/'identity.sealed').read_bytes()),
        capture_output=True,check=True).stdout)
assert identity.get('ctid') and identity.get('account')
manifest=json.loads((root/'BINARY_MANIFEST.json').read_text())
binary=root/'NativeHistorical.algo'
assert hashlib.sha256(binary.read_bytes()).hexdigest()==manifest['sha256']
if password!=root/'password.pwd':shutil.copyfile(password,root/'password.pwd')
(root/'password.pwd').chmod(0o600)
image_id=subprocess.run(docker+['image','inspect','ghcr.io/spotware/ctrader-console:latest',
    '--format','{{.Id}}'],capture_output=True,text=True,check=True).stdout.strip()
case=json.loads((root/'CASE.json').read_text())
assert case['symbol'] in ('EURUSD','XAUUSD','BTCUSD')
secret_values=[str(identity['ctid']),str(identity['account']),password.read_text().strip()]
(root/'data').mkdir(exist_ok=True)
container='rizan-native-m1-'+str(os.getpid())
args=['backtest','/mnt/test/NativeHistorical.algo',
    '--ctid='+str(identity['ctid']),'--pwd-file=/mnt/test/password.pwd',
    '--account='+str(identity['account']),'--symbol='+case['symbol'],'--period=m1',
    '--start='+case['start'],'--end='+case['end'],'--balance=100','--data-mode=m1',
    '--EnableTrading=true','--HistoricalTransport=true',
    '--EnableXau='+str(case.get('xau',False)).lower(),
    '--EnableEur='+str(case.get('eur',False)).lower(),
    '--EnableBtc='+str(case.get('btc',False)).lower(),
    '--data-dir=/mnt/test/data','--report-json=/mnt/test/report.json','--exit-on-stop']
command=docker+['run','--pull=never','--name',container,'--memory=4g','--cpus=2',
    '--mount','type=bind,src='+str(root)+',dst=/mnt/test',
    '-e','DOTNET_ROLL_FORWARD=Major',image_id]+args
result={'case':case,'binary':manifest,'image':image_id,
        'native_runtime':True,'ApiStubs':False,'cached_signals':False,
        'live_command_invoked':False,'credential_exported':False,'timeout':False}
print('NATIVE_M1_LAUNCH '+json.dumps(case),flush=True)
start=time.monotonic()
try:
    with (root/'native.log').open('w') as f:
        result['exit_code']=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,
            timeout=case.get('timeout_seconds',1200)).returncode
except subprocess.TimeoutExpired:
    result['timeout']=True
    subprocess.run(docker+['rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
finally:
    (root/'password.pwd').unlink(missing_ok=True)
result['elapsed_seconds']=round(time.monotonic()-start,2)
# Capture the native cTrader TXT/JSON event log from the stopped container.
import tarfile
proc=subprocess.Popen(docker+['export',container],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
try:
    with tarfile.open(fileobj=proc.stdout,mode='r|') as tar:
        for member in tar:
            name=member.name
            if member.isfile() and 'backtest' in name.lower() and name.lower().endswith(('.txt','.log','.json')) and member.size<50_000_000:
                data=tar.extractfile(member).read()
                out=root/'runtime-logs'/name
                out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
finally:
    proc.stdout.close();proc.wait()
    subprocess.run(docker+['rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
log=(root/'native.log').read_text(errors='replace')
for f in (root/'runtime-logs').rglob('*'):
    if f.is_file():log+='\n'+f.read_text(errors='replace')
for f in (root/'data').rglob('*'):
    if f.is_file() and f.suffix.lower() in ('.txt','.log'):log+='\n'+f.read_text(errors='replace')
# Export only bot-owned diagnostics. Never copy native account/auth lines.
prefixes=('NATIVE_BACKTEST_','NATIVE_SIGNAL ','NATIVE_ORDER_RESULT ','RIZAN_BATCH ',
          'RIZAN_STARTUP_OK','RIZAN_PORTFOLIO ready=','QUARANTINED:',
          'BROKER_CHILD_CONTRACT_MISMATCH','HEDGED_ACCOUNT_REQUIRED','USD_ACCOUNT_REQUIRED',
          'PORTFOLIO_ENGINE_START_ERROR','PORTFOLIO_ENGINE_START_FAILED')
safe=[line for line in log.splitlines() if any(p in line for p in prefixes)]
result['signal_count']=sum('NATIVE_SIGNAL ' in s for s in safe)
result['order_requests']=sum('NATIVE_ORDER_RESULT ' in s for s in safe)
result['accepted_orders']=sum('NATIVE_ORDER_RESULT ' in s and 'success=True' in s for s in safe)
result['quarantine_count']=sum('QUARANTINED:' in s for s in safe)
result['startup_ok']=any('RIZAN_STARTUP_OK' in s for s in safe)
result['summaries']=[s for s in safe if 'NATIVE_BACKTEST_SUMMARY' in s]
result['recent_bot_logs']=safe[-15:]
result['first_signals']=[s for s in safe if 'NATIVE_SIGNAL ' in s][:10]
result['first_orders']=[s for s in safe if 'NATIVE_ORDER_RESULT ' in s][:10]
result['native_report_created']=(root/'report.json').is_file()
result['error_categories']={name:any(word in log.lower() for word in words) for name,words in {
    'authentication':['invalid credentials','authentication failed','wrong password'],
    'no_data':['no historical data','no data available'],
    'unrecognized_parameter':['unknown option','unrecognized option','unknown parameter'],
    'memory':['outofmemory','out of memory'],
    'access_rights':['additional accessrights','full-access'],
    'runtime_exception':['exception','error on start']}.items()}
result['state_reasons']=dict((s,len(re.findall(re.escape(s),log))) for s in sorted(set(
    re.findall(r'\b(?:NO_[A-Z_]+|[A-Z_]+_REQUIRED|[A-Z_]+_BLOCK|WARMUP_[A-Z0-9_]+|VIRTUAL_HISTORY_GAP|LOCAL_CHECKPOINT_WRITE_FAILED|BACKTEST_ONLY_BUILD|RUNTIME_EXCEPTION:[A-Za-z0-9_]+)\b',log))))
if not result['native_report_created'] or result['timeout'] or result.get('exit_code')!=0:
    # Diagnostic error lines are redacted before export.
    bad=[s for s in log.splitlines() if any(x in s.lower() for x in ('error','exception','required','failed','unsupported','not found'))]
    secrets=secret_values
    for value in secrets:
        if value:bad=[s.replace(value,'[REDACTED]') for s in bad]
    result['errors_redacted']=bad[-10:]
result['native_log_files']=[str(p.relative_to(root/'runtime-logs')) for p in (root/'runtime-logs').rglob('*') if p.is_file()]
if (root/'report.json').is_file():
    report=json.loads((root/'report.json').read_text());result['report_keys']=list(report) if isinstance(report,dict) else str(type(report))
(root/'PUBLIC_RESULT.json').write_text(json.dumps(result,indent=2))
print('NATIVE_M1_RESULT '+json.dumps(result),flush=True)
raise SystemExit(0 if result.get('exit_code')==0 and not result['timeout'] else 2)

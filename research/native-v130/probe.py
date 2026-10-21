"""Run only metadata/backtest on VPS. Credentials and raw logs stay on VPS."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
os.umask(0o077)
context = json.loads((Path.home()/'.local/state/rizan-native-preflight/context.json').read_text())
docker = context['DockerPrefix']
assert docker and docker[-1].endswith('docker')
credentials = context['CredentialCandidates']
assert len(credentials) == 1, 'CREDENTIAL_NOT_UNIQUE'
password = Path(credentials[0])
assert password.is_file() and not password.is_symlink()
key = Path.home()/'.local/state/rizan-native-preflight/transfer.pem'
identity_bytes = subprocess.run(
    ['openssl','pkeyutl','-decrypt','-inkey',str(key),'-pkeyopt','rsa_padding_mode:oaep',
     '-pkeyopt','rsa_oaep_md:sha256','-pkeyopt','rsa_mgf1_md:sha256'],
    input=base64.b64decode((root/'identity.sealed').read_bytes()),
    capture_output=True,check=True).stdout
identity=json.loads(identity_bytes)
assert identity.get('ctid') and identity.get('account'), 'IDENTITY_INCOMPLETE'
algo=base64.b64decode((root/'FrozenV130.algo.b64').read_bytes())
digest=hashlib.sha256(algo).hexdigest()
assert digest == 'a3d00f27ebe1f4f9eec2ede99fe56ef581556c42492e6e04817be19b19003b9c'
(root/'FrozenV130.algo').write_bytes(algo)
shutil.copyfile(password,root/'password.pwd')
(root/'password.pwd').chmod(0o600)
image='ghcr.io/spotware/ctrader-console:latest'
image_id=subprocess.run(docker+['image','inspect',image,'--format','{{.Id}}'],capture_output=True,text=True,check=True).stdout.strip()
result={'binary_sha256':digest,'image_id':image_id,'native_algo':True,
        'mode':'backtest','start':'09/06/2025','end':'11/06/2025',
        'initial_balance':100,'services_changed':False,'live_run_invoked':False,
        'credential_exported':False,'full_2019_2026_completed':False,'runs':[]}
for name,args,limit in [
    ('version',['--version'],40),
    ('metadata',['metadata','/mnt/test/FrozenV130.algo'],60),
    ('backtest',['backtest','/mnt/test/FrozenV130.algo',
        '--ctid='+str(identity['ctid']),'--pwd-file=/mnt/test/password.pwd',
        '--account='+str(identity['account']),'--symbol=XAUUSD','--period=m1',
        '--start=09/06/2025','--end=11/06/2025','--balance=100','--data-mode=ticks',
        '--EnableTrading=true','--ExpectedAccount='+str(identity['account']),
        '--report-json=/mnt/test/report.json','--exit-on-stop'],360),
]:
    container='rizan-native-v130-'+str(os.getpid())+'-'+name
    command=docker+['run','--rm','--pull=never','--name',container,'--memory=256m','--cpus=0.5',
        '--mount','type=bind,src='+str(root)+',dst=/mnt/test',
        '-e','DOTNET_ROLL_FORWARD=Major',image_id]+args
    entry={'stage':name,'timeout':False}
    log=root/(name+'.log')
    try:
        with log.open('w') as f:
            run=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=limit)
        entry['exit_code']=run.returncode
    except subprocess.TimeoutExpired:
        entry['timeout']=True
        subprocess.run(docker+['rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    content=log.read_text(errors='replace')
    # Return only non-sensitive diagnostics, never stdout or identity fields.
    entry['markers']=sorted(set(re.findall(r'\b(?:PORTFOLIO_[A-Z_]+|RIZAN_STARTUP_OK|TRADING_DISABLED|[A-Z_]*BRIDGE[A-Z_]*|[A-Z_]*QUARANTINE[A-Z_]*)\b',content)))
    entry['runtime_versions']=re.findall(r'\b(?:5|6)\.\d+\.\d+(?:\.\d+)?\b',content)[:5]
    entry['possible_oom']=entry.get('exit_code')==137
    result['runs'].append(entry)
    if name=='metadata':
        try:
            metadata=json.loads(content[content.index('{'):])
            result['metadata']={k:metadata.get(k) for k in ('Name','Type','AccessRights')}
            result['parameters']=[{'name':p.get('PropertyName'),'default':p.get('DefaultValue')}
                                  for p in metadata.get('Parameters',[])
                                  if p.get('PropertyName') in ('EnableTrading','EnableXau','EnableEur','EnableBtc')]
        except (ValueError,TypeError):pass
    (root/'PUBLIC_RESULT.json').write_text(json.dumps(result,indent=2))
    if name=='metadata' and (entry.get('exit_code') != 0 or entry['timeout']):break
report=root/'report.json'
if report.exists():
    # Keep full report private until its format/identity fields are inspected.
    result['native_report_created']=True
else:result['native_report_created']=False
(root/'PUBLIC_RESULT.json').write_text(json.dumps(result,indent=2))
(root/'password.pwd').unlink(missing_ok=True)
print(json.dumps(result))
if any(r.get("exit_code") != 0 or r["timeout"] for r in result["runs"]):
    raise SystemExit(2)

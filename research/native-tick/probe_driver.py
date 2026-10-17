"""Isolated native backtest probe. Never invokes the live run command."""
import base64, gzip, hashlib, io, json, os, pathlib, subprocess, tarfile, traceback, urllib.request, zipfile
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
root=pathlib.Path(os.environ['RIZAN_NATIVE_PRIVATE'])
repo=pathlib.Path.cwd()
output={'kind':'native tick probe','tradingCommandsExecuted':False}
def execute(args,name,timeout=600,cwd=None):
    path=root/(name+'.log')
    with path.open('wb') as log:
        try:
            r=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,cwd=cwd)
            output[name+'Exit']=r.returncode
            return r.returncode
        except subprocess.TimeoutExpired:
            output[name+'Exit']='TIMEOUT';return -1
try:
    config=json.loads((root/'identity.json').read_text())
    sdk=root/'cli';sdk.mkdir()
    archive=root/'cli.tar.gz'
    urllib.request.urlretrieve('https://getctrader.spotware.com/cli/homebrew/ctrader-cli-5.9.0-linux-x64.tar.gz',archive)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest=='da0f5fb0c58980be9143fafca9839de784084b6e323321d9e03e5c3e64bec562','CLI_CHECKSUM'
    with tarfile.open(archive) as t:t.extractall(sdk,filter='data')
    for p in sdk.rglob('*'):
        if p.is_file() and ('.' not in p.name or p.name=='algohost.netcore'):p.chmod(0o700)
    cli=next(p for p in sdk.rglob('ctrader-cli') if p.is_file())
    execute([str(cli),'--version'],'version',60)
    auth=['--ctid='+config['ctid'],'--pwd-file='+str(root/'password.pwd'),'--account='+str(config['account'])]
    execute([str(cli),'account',*auth,'-q'],'account',90)
    for symbol in ['XAUUSD','EURUSD']:
        execute([str(cli),'symbol',*auth,'-q','--symbol='+symbol],'symbol_'+symbol,90)
    execute([str(cli),'--commands'],'help',60)
    execute([str(cli),'create','cbot','ProbeTemplate','csharp','-q'],'create',60,cwd=root)
    output['GeneratedProjects']={str(p.relative_to(root)):p.read_text() for p in root.rglob('*.csproj')}
    strategy=os.environ.get('RIZAN_NATIVE_STRATEGY')=='1'
    project=repo/'research/native-tick/probe/NativeTickProbe.csproj'
    if strategy:
        envelope=json.loads((repo/('research/native-tick/strategy-opt.sealed.json' if os.environ.get('RIZAN_NATIVE_VARIANT')=='optimized' else 'research/native-tick/strategy.sealed.json')).read_text())
        raw=AESGCM((root/'source-key').read_bytes()).decrypt(base64.b64decode(envelope['nonce']),base64.b64decode(envelope['ciphertext']),b'native-strategy-v1')
        folder=root/'strategy';folder.mkdir()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:z.extractall(folder)
        project=folder/'RizanPortfolio.csproj'
        output['kind']='native strategy smoke with historical macro permission proxy'
        output['SourceSHA256']={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.cs')}

    if execute(['dotnet','build',str(project),'-c','Release','-o',str(root/'build')],'build',300)==0:
        algos=list((root/'build').rglob('*.algo'))
        if not algos:algos=list(project.parent.rglob('*.algo'))
        output['AlgoCount']=len(algos)
        if algos:
            algo=algos[0]
            execute([str(cli),'metadata',str(algo)],'metadata',60)
            args=[str(cli),'backtest',str(algo),'--ctid='+config['ctid'],'--pwd-file='+str(root/'password.pwd'),'--account='+str(config['account']),'--symbol=XAUUSD','--period=m1','--start='+os.environ.get('RIZAN_NATIVE_START',('09/06/2025' if strategy else '10/06/2025')),'--end='+os.environ.get('RIZAN_NATIVE_END',('14/06/2025' if strategy else '11/06/2025')),'--balance=100','--data-mode=ticks','--report-json='+str(root/'report.json'),'--exit-on-stop']
            if not strategy and os.environ.get('RIZAN_NATIVE_FEE_BATCH')=='1':args+=['--FeeProbe=true','--commission=30']
            if strategy:output['CostScope']='execution smoke only; native CLI 5.9 lacks per-lot commission override; no performance certification'
            execute(args,'native_backtest',1200 if strategy else 900)
            if not strategy and os.environ.get('RIZAN_SKIP_COST_PROBE')!='1':
                execute([str(cli),'backtest','--algo-file='+str(algo),*auth,'-q','--symbol=XAUUSD','--period=m1','--from=2025-06-10','--to=2025-06-11','--data-mode=ticks','--balance=100','--commission=3','--commission-type=UsdPerOneLot','--FeeProbe=true','--exit-on-stop'],'interactive_cost_probe',900)
except Exception as e:
    output['exceptionType']=type(e).__name__
    output['exception']=str(e)
finally:
    # Only named diagnostic logs/reports are included, never credentials or config.
    output['logs']={p.name:p.read_text(errors='replace')[-300000:] for p in root.glob('*.log')}
    log=root/'native_backtest.log'
    if log.exists():
        markers=('NATIVE_','RIZAN_BATCH ','QUARANTIN','RIZAN_PORTFOLIO_START','Error |','Crashed','RUNTIME_EXCEPTION','BROKER_BATCH','RIZAN_STARTUP_OK','RIZAN_LATENCY','Create order','Execute','Close position')
        output['native_key_events']=[line for line in log.read_text(errors='replace').splitlines() if any(m in line for m in markers)][:20000]
    if (root/'report.json').exists():
        p=root/'report.json';output['report']=p.read_text(errors='replace')[:1000000]
    raw=gzip.compress(json.dumps(output).encode())
    key=os.urandom(32);nonce=os.urandom(12)
    public=serialization.load_pem_public_key((repo/'research/native-tick/result-public.pem').read_bytes())
    wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    envelope=json.dumps({'wrapped':base64.b64encode(wrapped).decode(),'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,raw,b'native-probe-v1')).decode()})
    encoded=base64.b64encode(envelope.encode()).decode()
    print('NATIVE_ENCRYPTED_BEGIN')
    for i in range(0,len(encoded),3000):print('NATIVE_CHUNK '+encoded[i:i+3000])
    print('NATIVE_ENCRYPTED_END')
    print('NATIVE_PROBE_STATUS '+json.dumps({k:v for k,v in output.items() if k.endswith('Exit') or k=='AlgoCount'}))

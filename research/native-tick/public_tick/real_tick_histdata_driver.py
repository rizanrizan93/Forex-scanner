"""Public real-quote replay fallback. All strategy, warmup and results stay encrypted."""
import os,pathlib,urllib.request,concurrent.futures,lzma,struct,datetime,json,subprocess,hashlib,base64,gzip,traceback,zipfile,io,time
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
root=pathlib.Path(os.environ['RIZAN_NATIVE_PRIVATE']);repo=pathlib.Path.cwd();out={'kind':'Actual public tick source harness; NOT native cTrader engine','LiveTradingCommandsExecuted':False,'MacroVintageCertified':False,'data_source':'Dukascopy public hourly bi5','audit':[]}
def command(args,name,timeout=1200):
 with (root/(name+'.log')).open('wb') as f:
  try:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=timeout);out[name+'Exit']=r.returncode;return r.returncode
  except subprocess.TimeoutExpired:out[name+'Exit']='TIMEOUT';return -1
def download(item):
 symbol,dt,h=item;errors=[]
 for host in ['www.dukascopy.com','datafeed.dukascopy.com']:
  url=f'https://{host}/datafeed/{symbol}/{dt.year}/{dt.month-1:02}/{dt.day:02}/{h:02}h_ticks.bi5'
  for attempt in range(2):
   try:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'*/*'});body=urllib.request.urlopen(req,timeout=12).read();raw=lzma.decompress(body) if body else b''
    if len(raw)%20:raise ValueError('BI5_BAD_LENGTH')
    return item,raw,{'symbol':symbol,'date':dt.isoformat(),'hour':h,'ticks':len(raw)//20,'url':url,'sha256':hashlib.sha256(body).hexdigest()}
   except Exception as e:errors.append(type(e).__name__+':'+str(e));time.sleep(1)
 return item,None,{'symbol':symbol,'date':dt.isoformat(),'hour':h,'errors':errors}
try:
 env=json.loads((repo/'research/native-tick/public-harness.sealed.json').read_text());env['ciphertext']=''.join((repo/'research/native-tick'/name).read_text().strip() for name in env['parts']);raw=AESGCM((root/'source-key').read_bytes()).decrypt(base64.b64decode(env['nonce']),base64.b64decode(env['ciphertext']),b'public-tick-harness-v1');folder=root/'source';folder.mkdir()
 with zipfile.ZipFile(io.BytesIO(raw)) as z:z.extractall(folder)
 out['source_hashes']={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.cs')}
 if command(['dotnet','build',str(folder/'TickResearch.csproj'),'-c','Release','-o',str(root/'build')],'build',300)!=0:raise RuntimeError('COMPILE_FAILED')
 import importlib.util
 spec=importlib.util.spec_from_file_location('histdata_fetch',repo/'research/native-tick/public_tick/histdata_fetch.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 rows=[]
 for symbol in ['EURUSD','XAUUSD']:
  data,audit=module.fetch(symbol);rows.extend(data);out['audit'].append(audit)
 out['downloaded_ticks']=len(rows);out['data_source']='HistData Generic ASCII bid/ask; sampled tick/one-second resolution; not full broker tick stream'
 rows.sort(key=lambda x:(x[0],x[1]));data=root/'quotes.bin'
 with data.open('wb') as f:
  for r in rows:f.write(struct.pack('<qBdd',*r))
 out['ticks_sha256']=hashlib.sha256(data.read_bytes()).hexdigest();out['TickCount']=len(rows)
 rc=command(['dotnet',str(root/'build/TickResearch.dll'),str(folder),str(data),str(root/'result.json')],'replay',1200)
 if (root/'result.json').exists():out['result']=json.loads((root/'result.json').read_text())
except Exception as e:out['error']=type(e).__name__+':'+str(e);out['traceback']=traceback.format_exc()
finally:
 out['logs']={p.name:p.read_text(errors='replace')[-80000:] for p in root.glob('*.log')}
 key=os.urandom(32);nonce=os.urandom(12);pub=serialization.load_pem_public_key((repo/'research/native-tick/result-public.pem').read_bytes());wrapped=pub.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None));env={'wrapped':base64.b64encode(wrapped).decode(),'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,gzip.compress(json.dumps(out).encode()),b'native-probe-v1')).decode()};encoded=base64.b64encode(json.dumps(env).encode()).decode()
 for i in range(0,len(encoded),3000):print('NATIVE_CHUNK '+encoded[i:i+3000])

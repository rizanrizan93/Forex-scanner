"""Read public historical quotes and validate native CSV import. No live orders."""
import os,pathlib,urllib.request,concurrent.futures,lzma,struct,datetime,json,subprocess,hashlib,base64,gzip,traceback
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
root=pathlib.Path(os.environ['RIZAN_NATIVE_PRIVATE']);repo=pathlib.Path.cwd();image='ghcr.io/spotware/ctrader-console@sha256:285484fad431e0ffa4ca96662e82ea66cead93c97cf0e3c46006e80cab4734ba'
out={'kind':'public actual tick native CSV import validation','LiveTradingCommandsExecuted':False,'BacktestOnly':True,'RuntimeImage':image,'data_source':'Dukascopy public hourly bi5','datasets':[]}
def command(args,name,timeout=300):
 container=None
 if args[0]=='NATIVE':
  container='rizan-public-'+os.urandom(6).hex();args=['docker','run','--rm','--name',container,'-v',str(root)+':'+str(root),'-v',str(repo)+':'+str(repo),'-e','DOTNET_ROLL_FORWARD=Major',image]+args[1:]
 with (root/(name+'.log')).open('wb') as f:
  try:r=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=timeout);out[name+'Exit']=r.returncode;return r.returncode
  except subprocess.TimeoutExpired:out[name+'Exit']='TIMEOUT';return -1
  finally:
   if container:subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def hour(symbol,date,h):
 dt=datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc)+datetime.timedelta(hours=h)
 url=f'https://datafeed.dukascopy.com/datafeed/{symbol}/{dt.year}/{dt.month-1:02}/{dt.day:02}/{h:02}h_ticks.bi5'
 failure=None
 for attempt in range(3):
  try:
   body=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RizanHistoricalResearch/1.0'}),timeout=25).read()
   raw=lzma.decompress(body) if body else b''
   if len(raw)%20:raise ValueError('BI5_LENGTH')
   return h,raw,hashlib.sha256(body).hexdigest(),url
  except Exception as e:failure=type(e).__name__+':'+str(e)
 raise RuntimeError(url+' '+str(failure))
try:
 cfg=json.loads((root/'identity.json').read_text());auth=['--ctid='+cfg['ctid'],'--pwd-file='+str(root/'password.pwd'),'--account='+str(cfg['account'])]
 command(['docker','pull',image],'pull')
 project=repo/'research/native-tick/public_tick/PublicTickProbe.csproj'
 if command(['dotnet','build',str(project),'-c','Release','-o',str(root/'build')],'build')!=0:raise RuntimeError('BUILD')
 algos=list((root/'build').rglob('*.algo')) or list(project.parent.rglob('*.algo'));algo=algos[0]
 for symbol in ['XAUUSD','EURUSD']:
  date='2019-01-07';rows=[];audit=[];scale=1000 if symbol=='XAUUSD' else 100000
  with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
   parts=list(pool.map(lambda h:hour(symbol,date,h),range(24)))
  for h,raw,digest,url in sorted(parts):
   audit.append({'hour':h,'ticks':len(raw)//20,'sha256':digest,'url':url})
   start=datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc)+datetime.timedelta(hours=h)
   for ms,ask,bid,av,bv in struct.iter_unpack('>3I2f',raw):
    if ms>=3600000 or bid<=0 or ask<bid:raise ValueError('INVALID_QUOTE')
    rows.append((start+datetime.timedelta(milliseconds=ms),bid/scale,ask/scale))
  if not rows or any(a[0]>b[0] for a,b in zip(rows,rows[1:])):raise ValueError('EMPTY_OR_UNSORTED')
  ds={'symbol':symbol,'date':date,'count':len(rows),'first':[str(rows[0][0]),*rows[0][1:]],'last':[str(rows[-1][0]),*rows[-1][1:]],'hours':audit};out['datasets'].append(ds)
  # CSV formats are tried only for parser compatibility; all quotes and order remain intact.
  for fmt in range(3):
   csv=root/(symbol+f'_{fmt}.csv')
   with csv.open('w') as f:
    if fmt==0:f.write('Time,Bid,Ask\n')
    for dt,bid,ask in rows:
     t=dt.strftime('%Y.%m.%d %H:%M:%S.%f')[:-3] if fmt!=2 else dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
     f.write(f'{t},{bid:.5f},{ask:.5f}\n')
   name=symbol+'_csv'+str(fmt)
   rc=command(['NATIVE','backtest',str(algo),*auth,'--symbol='+symbol,'--period=m1','--start=07/01/2019','--end=08/01/2019','--balance=100','--data-mode=tick-csv','--data-file='+str(csv),'--commission-auto','--precise-conversion','--report-json='+str(root/(name+'.json')),'--exit-on-stop'],name,180)
   log=(root/(name+'.log')).read_text(errors='replace')
   if 'PUBLIC_PROBE_RESULT' in log:
    ds['working_csv_format']=fmt;ds['native_exit']=rc;break
except Exception as e:out['error']=type(e).__name__+':'+str(e);out['traceback']=traceback.format_exc()
finally:
 out['logs']={p.name:p.read_text(errors='replace')[-60000:] for p in root.glob('*.log')}
 key=os.urandom(32);nonce=os.urandom(12);pub=serialization.load_pem_public_key((repo/'research/native-tick/result-public.pem').read_bytes());wrapped=pub.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
 env={'wrapped':base64.b64encode(wrapped).decode(),'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(AESGCM(key).encrypt(nonce,gzip.compress(json.dumps(out).encode()),b'native-probe-v1')).decode()}
 enc=base64.b64encode(json.dumps(env).encode()).decode()
 for i in range(0,len(enc),3000):print('NATIVE_CHUNK '+enc[i:i+3000])

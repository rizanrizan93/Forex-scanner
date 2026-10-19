import pathlib,zipfile,json,csv,io,gzip,hashlib,re,os
import pandas as pd
ROOT=pathlib.Path.cwd();SRC=ROOT/'original';OUT=ROOT/'compact';OUT.mkdir(exist_ok=True)
def clean(x):
 if isinstance(x,float) and not __import__('math').isfinite(x):return None
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
 if isinstance(x,list):return [clean(v) for v in x]
 return x
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
status=clean(json.loads((SRC/'FINAL_STATUS.json').read_text()));compare=pd.read_csv(SRC/'ALL_LEADER_RESULTS.csv')
for name in ['LAPORAN_BTCUSD_USDJPY_2019_2026.md','FINAL_COMPARISON.csv','ALL_LEADER_RESULTS.csv','ALL_SELECTED_SCENARIOS.csv','CASH_RECONCILIATION.json','CONFIGURATIONS.json','UNIVERSE_STATISTICS.json','GLOBAL_UNIQUE_PARAMETER_COUNTS.json','FINAL_STATUS.json','VPS_STORAGE_RECEIPT.json']:
 p=SRC/name
 if p.exists():
  if p.suffix=='.json':(OUT/name).write_text(json.dumps(clean(json.loads(p.read_text())),indent=2,allow_nan=False))
  else:(OUT/name).write_bytes(p.read_bytes())
addendum='''# Model validity and compact archive notes

These are historical M1 model results, not native broker or real bid/ask tick validation. BTC leverage10 remains an unverified research assumption; leverage2 sensitivity is separate. USDJPY model leverage200 is likewise not historical account certification.

The common engine has a permanent capital-floor stop after a completed trade: cash<=0, or positive cash below minUnit*signalBid/(2*leverage) forBTC, and minUnit/(2*leverage) forUSDJPY. This is an assumed account-deactivation policy. It does not model reactivation if later crypto prices make a minimum lot affordable. Therefore the negative target finding is conditional on this policy; it is not a proof that no possible strategy or recovery policy can reach100k. The main nominal selected leaders are separately checked below against the maximum floor over the actual data.

Drawdown is the chosen OHLC stress/envelope statistic. STOP_FIRST does not prove the true intraminute path or actual maximum drawdown. Snapshot prices, quote spread, financing, slippage, leverage tiers, execution hours, rejection/ACK/recovery and broker minimum-stop/grid rounding remain model assumptions.

This compact archive retains all3million configuration rows per instrument, actual source/parameters, canonical full-period M1 input, every selected raw transaction ledger and stress table, selected equity curves/charts, monthly/yearly summaries and provenance. Large redundant intermediate equity-curve CSVs and March-control data are omitted by file type, not by performance. The original complete archives remain unchanged in GitHub Actions39217369074 and the recorded VPS folder.

Non-applicable NaN report fields are normalized to JSONnull. Financial results and configuration rows are unchanged. Every retained compact file has a fresh complete SHA256 manifest.
'''
(OUT/'MODEL_VALIDITY_ADDENDUM.md').write_text(addendum)
receipt={}
for symbol in ['BTCUSD','USDJPY']:
 original=SRC/('RIZAN_'+symbol+'_MILLION_M1_2019_2026.zip')
 with zipfile.ZipFile(original) as zin:
  fullleaders=compare[compare.symbol==symbol]
  keepids={}
  for variant,g in fullleaders.groupby('variant'):keepids[variant]=set(int(i) for i in g.id)
  datafile='FULL_PERIOD/GENERIC/data/'+symbol+'_M1.csv.gz'
  maxopen=0.
  with gzip.GzipFile(fileobj=zin.open(datafile)) as gz:
   for row in csv.DictReader(io.TextIOWrapper(gz)):maxopen=max(maxopen,float(row['open']))
  maxfloor=(.01*maxopen/(2*10)) if symbol=='BTCUSD' else 1000/(2*200)
  chosen=status['leaders'];check=[{'id':x['id'],'criterion':x['criterion'],'ending_cash':x['equity'],'maximum_model_floor':maxfloor,'nominal_leader_not_stopped_by_floor':x['equity']>=maxfloor} for x in chosen if x['symbol']==symbol]
  receipt[symbol]={'original_full_archive_sha256':sha(original),'max_observed_signal_bid':maxopen,'capital_floor_check':check}
  zpath=OUT/('RIZAN_'+symbol+'_RESEARCH_COMPACT_2019_2026.zip');manifest=[];omitted=[]
  with zipfile.ZipFile(zpath,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4) as zout:
   def put(name,b):
    zout.writestr(name,b);manifest.append([name,hashlib.sha256(b).hexdigest(),len(b)])
   for n in zin.namelist():
    if n.endswith('/'):continue
    parts=n.split('/')
    if n.startswith('MARCH_LOCKED_CONTROLS/'):
     omitted.append(n);continue
    if parts[-1]=='MANIFEST_SHA256.csv' or '__pycache__' in parts:omitted.append(n);continue
    if n.startswith('FULL_PERIOD/') and re.match(r'candidate_\d+_(equity|ledger|month|year)',parts[-1]):omitted.append(n);continue
    m=re.search(r'^FULL_PERIOD/([^/]+)/raw_validation/raw_(\d+)_equity.csv$',n)
    if m and int(m.group(2)) not in keepids.get(m.group(1),set()):omitted.append(n);continue
    b=zin.read(n)
    if n.endswith('.json'):
     try:b=json.dumps(clean(json.loads(b)),indent=2,allow_nan=False).encode()
     except Exception:pass
    put(n,b)
   put('MODEL_VALIDITY_ADDENDUM.md',addendum.encode())
   put('CAPITAL_FLOOR_LEADER_CHECK.json',json.dumps(receipt[symbol],indent=2,allow_nan=False).encode())
   put('ORIGINAL_ARCHIVE_REFERENCE.json',json.dumps({'full_archive':original.name,'sha256':receipt[symbol]['original_full_archive_sha256'],'actions_run':39217369074,'compact_omissions':omitted},indent=2).encode())
   stream=io.StringIO();w=csv.writer(stream);w.writerow(['path','sha256','bytes']);w.writerows(manifest);zout.writestr('MANIFEST_SHA256.csv',stream.getvalue())
  with zipfile.ZipFile(zpath) as z:
   assert z.testzip() is None
   for name,expected,size in manifest:
    b=z.read(name);assert len(b)==size and hashlib.sha256(b).hexdigest()==expected
  assert zpath.stat().st_size<500*1024*1024
  print('COMPACT_VERIFIED',symbol,zpath.stat().st_size,sha(zpath),flush=True)
  for x in status['leaders']:
   if x['symbol']==symbol and x['criterion'] in ['FULL','DD50']:
    path='FULL_PERIOD/'+x['variant']+'/raw_validation/raw_'+str(x['id'])+'_equity_drawdown.png'
    (OUT/(symbol+'_'+x['criterion']+'_equity_drawdown.png')).write_bytes(zin.read(path))
dump=lambda p,x:pathlib.Path(p).write_text(json.dumps(x,indent=2,allow_nan=False))
dump(OUT/'COMPACT_VALIDATION.json',receipt)
with open(OUT/'COMPACT_SHA256.txt','w') as f:
 for p in sorted(OUT.iterdir()):
  if p.is_file() and p.name!='COMPACT_SHA256.txt':f.write(sha(p)+'  '+p.name+'\n')

"""Exact-byte EUR archive acquisition and M5 quote aggregation for USD proxy."""
import pathlib,json,csv,io,hashlib,urllib.request,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import pyarrow.parquet as pq
import numpy as np,pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1];DATA=ROOT/'data_eur';DATA.mkdir(exist_ok=True);OUT=ROOT/'r2_audit';OUT.mkdir(exist_ok=True)
inventory=json.loads((ROOT/'audit/vps_inventory.json').read_text());rows=list(csv.DictReader(io.StringIO(inventory['manifests']['.jobs/manifest_sha256.csv'])))
def get(r):
 p=DATA/r['filename']
 for attempt in range(3):
  try:
   if not p.exists() or p.stat().st_size!=int(r['bytes']):
    tmp=p.with_suffix('.partial');urllib.request.urlretrieve(r['source_url'],tmp);tmp.replace(p)
   sha=hashlib.sha256(p.read_bytes()).hexdigest()
   if sha!=r['sha256']:raise ValueError('SHA256_MISMATCH')
   return {'file':p.name,'sha256':sha,'bytes':p.stat().st_size,'source_url':r['source_url'],'status':'MATCH_VPS_MANIFEST'}
  except Exception as e:
   if attempt==2:return {'file':p.name,'status':'ERROR','error':str(e)}
   time.sleep(1+attempt)
if __name__=='__main__':
 selected=[r for r in rows if r['symbol']=='EURUSD' and r['filename']<='EURUSD_2026-03.parquet'];records=[]
 with ThreadPoolExecutor(max_workers=4) as ex:
  for f in as_completed([ex.submit(get,r) for r in selected]):records.append(f.result());print(len(records),records[-1]['file'],records[-1]['status'],flush=True)
 (OUT/'eur_manifest.json').write_text(json.dumps(sorted(records,key=lambda x:x['file']),indent=2))
 parts=[];audit=[]
 for p in sorted(DATA.glob('EURUSD_*.parquet')):
  t=pq.read_table(p,columns=['timestamp','bid','ask']);meta=t.schema.metadata or {};point=float(meta.get(b'point',b'100000'))
  if point!=100000 or meta.get(b'symbol')!=b'EURUSD':raise ValueError('Bad EUR schema')
  ts=t['timestamp'].cast('int64').to_numpy();bid=t['bid'].to_numpy()/point;ask=t['ask'].to_numpy()/point
  if (np.diff(ts)<0).any() or (ask<bid).any() or (bid<=0).any():raise ValueError('Invalid EUR quote')
  d=pd.DataFrame({'eur':(bid+ask)/2,'spread':ask-bid},index=pd.to_datetime(ts,unit='ms',utc=True))
  b=d.resample('5min').agg(eur=('eur','last'),spread=('spread','mean'));b['quote_ms']=pd.Series(ts,index=d.index).resample('5min').last();parts.append(b)
  audit.append({'file':p.name,'rows':len(ts),'first':str(d.index.min()),'last':str(d.index.max())});print('BARS',p.name,flush=True)
 pd.concat(parts).to_parquet(ROOT/'derived/eur_m5.parquet');(OUT/'eur_integrity.json').write_text(json.dumps(audit,indent=2))

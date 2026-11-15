"""Weekly ALFRED point-in-time snapshots, each column independently verified.

Critical: one scalar vintage_date on a multi-series URL only dates the FIRST
series. Send one date PER series and reject any unexpected date suffix.
"""
import pathlib,json,hashlib,io,gzip,datetime,urllib.request,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd,numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1];RAW=ROOT/'r2_raw/alfred';RAW.mkdir(parents=True,exist_ok=True);OUT=ROOT/'r2_audit';OUT.mkdir(exist_ok=True)
IDS=['DGS2','DGS10','DFII10']
def validate(raw,day):
 d=pd.read_csv(io.BytesIO(raw));stamp=day.strftime('%Y%m%d');expected=['observation_date']+[s+'_'+stamp for s in IDS]
 if list(d.columns)!=expected:raise ValueError('VINTAGE_HEADER_MISMATCH '+str(list(d.columns)))
 d.columns=['date']+IDS;d['date']=pd.to_datetime(d.date)
 if (d.date>day).any():raise ValueError('FUTURE_OBSERVATION')
 return d
def task(day):
 ds=day.strftime('%Y-%m-%d');p=RAW/(ds+'.csv.gz');vintage=','.join([ds]*3)
 url=f'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=DGS2,DGS10,DFII10&vintage_date={vintage}&cosd={(day-pd.Timedelta(days=20)).strftime("%Y-%m-%d")}&coed={ds}'
 for attempt in range(3):
  try:
   if p.exists():raw=gzip.decompress(p.read_bytes())
   else:
    raw=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RIZAN-Research-R2/1.0'}),timeout=40).read();validate(raw,day);p.write_bytes(gzip.compress(raw))
   d=validate(raw,day);row={'vintage_date':ds,'available_at':(day.tz_localize('UTC')+pd.Timedelta(days=1,hours=12)).isoformat()}
   for s in IDS:
    q=d[['date',s]].dropna().tail(2)
    if len(q)!=2:raise ValueError('INSUFFICIENT_HISTORY '+s)
    row[s]=float(q[s].iloc[-1]);row[s+'_delta_bp']=float(q[s].diff().iloc[-1]*100);row[s+'_observation_date']=q.date.iloc[-1].strftime('%Y-%m-%d')
   meta={'vintage_date':ds,'file':str(p.relative_to(ROOT)),'url':url,'sha256_uncompressed':hashlib.sha256(raw).hexdigest(),'bytes_uncompressed':len(raw),'header_verified':True,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
   return row,meta
  except Exception as e:
   if attempt==2:return None,{'vintage_date':ds,'url':url,'error':str(e)}
   time.sleep(1+attempt)
if __name__=='__main__':
 dates=pd.date_range('2018-12-29','2026-03-28',freq='W-SAT');rows=[];manifest=[]
 with ThreadPoolExecutor(max_workers=4) as ex:
  for fut in as_completed([ex.submit(task,d) for d in dates]):
   row,meta=fut.result();manifest.append(meta)
   if row:rows.append(row)
   print(len(manifest),meta['vintage_date'],'OK' if row else meta.get('error'),flush=True)
 pd.DataFrame(rows).sort_values('available_at').to_csv(OUT/'alfred_weekly_pit.csv',index=False);(OUT/'alfred_manifest.json').write_text(json.dumps(sorted(manifest,key=lambda x:x['vintage_date']),indent=2))

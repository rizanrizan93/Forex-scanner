import pathlib,json,datetime as dt,urllib.request,hashlib,lzma,struct,time,concurrent.futures
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
r=pathlib.Path(__file__).resolve().parent; old=pathlib.Path('/tmp/previous');out=r/'gap_repair';out.mkdir(exist_ok=True);raw=out/'bi5';raw.mkdir(exist_ok=True)
gaps=json.load(open(old/'data_audit/gaps.json'));UTC=dt.timezone.utc
start=dt.datetime(2025,10,10,20,tzinfo=UTC);end=dt.datetime(2025,10,20,1,tzinfo=UTC)
jobs={('XAUUSD',start+dt.timedelta(hours=i)):'CRITICAL_FULL_RANGE' for i in range(int((end-start).total_seconds()/3600))}
classified=[]
for g in gaps:
 a=dt.datetime.fromisoformat(g['from']);b=dt.datetime.fromisoformat(g['to']);probes=[];t=a.replace(minute=0,second=0,microsecond=0)+dt.timedelta(hours=1)
 while t<b:
  if t.weekday()<5 and 12<=t.hour<20 and (t.month,t.day) not in [(1,1),(12,25)]:probes.append(t)
  t+=dt.timedelta(hours=1)
 # Only spans >=6h with internal weekday session hours; do not bless Christmas/Good Friday automatically.
 if g['seconds']>=21600 and probes:
  mid=probes[len(probes)//2];jobs.setdefault((g['symbol'],mid),'OTHER_CANDIDATE_PROBE')
  classified.append({**g,'reclassified':'WEEKDAY_SESSION_OVERLAP_REQUIRES_SOURCE_CHECK','probe_utc':mid.isoformat()})
 else:classified.append({**g,'reclassified':'CALENDAR_CANDIDATE_UNCERTIFIED' if g['classification']!='unexplained_review_required' else 'UNEXPLAINED'})
json.dump(classified,open(out/'RECLASSIFIED_GAPS.json','w'),indent=2)
def fetch(job):
 (sym,t),purpose=job;rel=f'{sym}/{t.year}/{t.month-1:02}/{t.day:02}/{t.hour:02}h_ticks.bi5';name=rel.replace('/','_');events=[]
 for base in ['https://datafeed.dukascopy.com/datafeed/','https://www.dukascopy.com/datafeed/']:
  u=base+rel
  try:
   req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (historical research; frozen strategy audit)'})
   with urllib.request.urlopen(req,timeout=25) as resp:b=resp.read();status=resp.status
   path=raw/name;path.write_bytes(b)
   dec=lzma.decompress(b) if b else b''
   assert len(dec)%20==0
   arr=np.frombuffer(dec,dtype=[('ms','>u4'),('ask','>u4'),('bid','>u4'),('ask_volume','>f4'),('bid_volume','>f4')])
   assert np.all(arr['ms']<3600000) and np.all(np.diff(arr['ms'].astype('i8'))>=0)
   assert np.all(arr['bid']<=arr['ask']) and np.all(arr['bid']>0)
   assert np.isfinite(arr['ask_volume']).all() and np.isfinite(arr['bid_volume']).all() and (arr['ask_volume']>=0).all() and (arr['bid_volume']>=0).all()
   info={'symbol':sym,'hour_utc':t.isoformat(),'purpose':purpose,'url':u,'http':status,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'ticks':len(arr),'errors':events,'status':'VERIFIED_DECODE' if len(arr) else 'EMPTY_NO_TICKS'}
   frame=pd.DataFrame({'timestamp':pd.to_datetime(int(t.timestamp()*1000)+arr['ms'].astype('i8'),unit='ms',utc=True),'bid':arr['bid'].astype('i8'),'ask':arr['ask'].astype('i8'),'bid_volume':arr['bid_volume'].astype(float),'ask_volume':arr['ask_volume'].astype(float)})
   return info,frame
  except Exception as e:events.append({'url':u,'error':repr(e)})
 return {'symbol':sym,'hour_utc':t.isoformat(),'purpose':purpose,'status':'FETCH_FAILED','errors':events},None
reports=[];frames=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
 for info,frame in ex.map(fetch,sorted(jobs.items())):
  reports.append(info)
  if frame is not None and info['symbol']=='XAUUSD' and info['purpose']=='CRITICAL_FULL_RANGE':frames.append(frame)
  print(info['symbol'],info['hour_utc'],info['status'],info.get('ticks',0),flush=True)
  json.dump(reports,open(out/'HOURLY_PROVENANCE.json','w'),indent=2)
if frames:
 d=pd.concat(frames).sort_values('timestamp',kind='stable');left=pd.Timestamp('2025-10-10T20:59:58.594Z');right=pd.Timestamp('2025-10-20T00:00:00.040Z')
 # Keep originals outside the strict missing interval for independent scale/sequence calibration.
 table=pa.Table.from_pandas(d,preserve_index=False);table=table.replace_schema_metadata({b'point':b'1000',b'provenance':b'Dukascopy original hourly bi5; UTC; no interpolation'})
 pq.write_table(table,out/'XAUUSD_recovered_with_overlap.parquet',compression='zstd')
 patch=d[(d.timestamp>left)&(d.timestamp<right)];table=pa.Table.from_pandas(patch,preserve_index=False).replace_schema_metadata(table.schema.metadata);pq.write_table(table,out/'XAUUSD_gap_patch.parquet',compression='zstd')
 spread=(patch.ask-patch.bid)/1000
 summary={'status':'RECOVERED_PENDING_OVERLAP_CALIBRATION' if len(patch) else 'DATA_GAP_UNRESOLVED','ticks_added':len(patch),'first':str(patch.timestamp.min()),'last':str(patch.timestamp.max()),'days':patch.timestamp.dt.strftime('%Y-%m-%d').value_counts().sort_index().to_dict(),'spread':spread.describe(percentiles=[.5,.95,.99]).to_dict(),'parquet_sha256':hashlib.sha256((out/'XAUUSD_gap_patch.parquet').read_bytes()).hexdigest()}
else:summary={'status':'DATA_GAP_UNRESOLVED','ticks_added':0}
summary['hour_results']={s:sum(v['status']==s for v in reports) for s in sorted({v['status'] for v in reports})};json.dump(summary,open(out/'GAP_REPAIR_SUMMARY.json','w'),indent=2);print(json.dumps(summary),flush=True)

from pathlib import Path
import json,lzma,hashlib,datetime as dt
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
r=Path(__file__).resolve().parent;out=r/'gap_repair';old=Path('/tmp/previous');gaps=[g for g in json.load(open(old/'data_audit/gaps.json'))if g['symbol']=='XAUUSD'and g['seconds']>36*3600 and g['from'].startswith(('2025-10-10','2025-12-30'))];assert len(gaps)==2
files={};manifest=[]
for folder in [out/'bi5',r/'extended_hour_recovery',r/'four_hour_recovery']:
 for p in sorted(folder.glob('*.bi5')):
  h=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
  if p.name in files:assert files[p.name][1]==h,('ORIGINAL_ARCHIVE_CHANGED',p.name);continue
  files[p.name]=(p,h)
frames=[]
for name,(p,h)in sorted(files.items()):
 a=name.split('_');assert a[0]=='XAUUSD';t=dt.datetime(int(a[1]),int(a[2])+1,int(a[3]),int(a[4][:2]),tzinfo=dt.timezone.utc);b=p.read_bytes();raw=lzma.decompress(b)if b else b'';assert len(raw)%20==0
 arr=np.frombuffer(raw,dtype=[('ms','>u4'),('ask','>u4'),('bid','>u4'),('ask_volume','>f4'),('bid_volume','>f4')]);assert (arr['ms']<3600000).all()and(np.diff(arr['ms'].astype('i8'))>=0).all()and(arr['bid']<=arr['ask']).all()
 d=pd.DataFrame({'timestamp':pd.to_datetime(int(t.timestamp()*1000)+arr['ms'].astype('i8'),unit='ms',utc=True),'bid':arr['bid'].astype('i8'),'ask':arr['ask'].astype('i8'),'bid_volume':arr['bid_volume'].astype(float),'ask_volume':arr['ask_volume'].astype(float)})
 mask=np.zeros(len(d),dtype=bool)
 for g in gaps:mask|=(d.timestamp>pd.Timestamp(g['from']))&(d.timestamp<pd.Timestamp(g['to']))
 piece=d.loc[mask];frames.append(piece);manifest.append({'file':name,'sha256':h,'original_ticks':len(d),'added_in_confirmed_empty_intervals':len(piece),'hour_utc':t.isoformat(),'source_local_path':str(p.relative_to(r))})
patch=pd.concat(frames,ignore_index=True).sort_values('timestamp',kind='stable');assert (patch.bid>0).all()and(patch.ask>=patch.bid).all()and np.isfinite(patch[['bid_volume','ask_volume']]).all().all()
pq.write_table(pa.Table.from_pandas(patch,preserve_index=False).replace_schema_metadata({b'point':b'1000',b'provenance':b'Original Dukascopy BI5; exact original hourly sequence; only confirmed empty Oct/Dec intervals; no interpolation'}),out/'XAUUSD_gap_patch.parquet',compression='zstd')
coverage=[]
# Every normally open hourly archive in the long October gap must be decoded. Weekend/21h maintenance remain explicitly excluded by schedule.
for day in range(12,20):
 for hour in range(24):
  t=dt.datetime(2025,10,day,hour,tzinfo=dt.timezone.utc)
  isopen=(t.weekday()<4 and hour!=21)or(t.weekday()==4 and hour<21)or(t.weekday()==6 and hour>=22)
  if isopen:
   name=f'XAUUSD_2025_09_{day:02}_{hour:02}h_ticks.bi5';v=next((x for x in manifest if x['file']==name),None);coverage.append({'hour_utc':t.isoformat(),'verified_archive':v is not None,'ticks':v['original_ticks']if v else None})
summary={'status':'RECOVERED_WITH_REMAINING_CALENDAR_REVIEW','ticks_added':len(patch),'by_month':patch.timestamp.dt.strftime('%Y-%m').value_counts().sort_index().to_dict(),'by_day':patch.timestamp.dt.strftime('%Y-%m-%d').value_counts().sort_index().to_dict(),'parquet_sha256':hashlib.file_digest((out/'XAUUSD_gap_patch.parquet').open('rb'),'sha256').hexdigest(),'first':str(patch.timestamp.min()),'last':str(patch.timestamp.max()),'october_expected_open_hours':len(coverage),'october_verified_open_hours':sum(x['verified_archive']for x in coverage),'october_missing_open_hours':[x for x in coverage if not x['verified_archive']],'duplicate_timestamps_retained':int(patch.timestamp.duplicated().sum()),'backward_timestamps':int((patch.timestamp.diff().dropna()<pd.Timedelta(0)).sum()),'bid_gt_ask':int((patch.bid>patch.ask).sum()),'spread':((patch.ask-patch.bid)/1000).describe(percentiles=[.5,.95,.99]).to_dict(),'gap_intervals':gaps,'calendar_schedule_assumption':'October EDT season: Sun22 to Fri21 UTC; weekday21-22 maintenance. HTTP failure never proves closure. Other original gaps still require calendar review.'}
json.dump(summary,open(out/'GAP_REPAIR_SUMMARY.json','w'),indent=2);json.dump(manifest,open(out/'MERGED_HOURLY_CHECKSUM_PROVENANCE.json','w'),indent=2);json.dump(coverage,open(out/'OCTOBER_OPEN_HOUR_COVERAGE.json','w'),indent=2);print(json.dumps(summary),flush=True)

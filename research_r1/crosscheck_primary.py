"""Sample archival rows against the original Dukascopy hourly tick feed."""
import lzma,urllib.request,json,pathlib,hashlib
import numpy as np,pandas as pd,pyarrow.parquet as pq
ROOT=pathlib.Path(__file__).resolve().parents[1];rawdir=ROOT/'primary_samples';rawdir.mkdir(exist_ok=True)
out=[]
for hour in ['2019-01-02T01:00:00Z','2022-01-03T01:00:00Z','2025-01-02T01:00:00Z','2026-03-02T01:00:00Z']:
 dt=pd.Timestamp(hour);url=f'https://datafeed.dukascopy.com/datafeed/XAUUSD/{dt.year}/{dt.month-1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5'
 result={'hour':hour,'url':url}
 try:
  raw=urllib.request.urlopen(url,timeout=30).read();(rawdir/(hour[:13].replace(':','-')+'.bi5')).write_bytes(raw)
  a=np.frombuffer(lzma.decompress(raw),dtype=np.dtype([('ms','>u4'),('ask','>u4'),('bid','>u4'),('av','>f4'),('bv','>f4')]))
  table=pq.read_table(ROOT/'data'/f'XAUUSD_{dt.year}-{dt.month:02d}.parquet',filters=[('timestamp','>=',dt.to_pydatetime()),('timestamp','<',(dt+pd.Timedelta(hours=1)).to_pydatetime())],columns=['timestamp','ask','bid'])
  b=table.to_pandas();times=b.timestamp.astype('int64').to_numpy()//1000000-int(dt.timestamp()*1000)
  match=len(b)==len(a) and np.array_equal(times,a['ms']) and np.array_equal(b.ask,a['ask']) and np.array_equal(b.bid,a['bid'])
  result.update(primary_rows=len(a),archive_rows=len(b),exact_price_time_match=bool(match),sha256=hashlib.sha256(raw).hexdigest())
 except Exception as e:result['error']=str(e)
 out.append(result);print(result,flush=True)
(ROOT/'audit/primary_crosscheck.json').write_text(json.dumps(out,indent=2))

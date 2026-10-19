"""Build entire BTCUSD minute input from official historical Bitstamp OHLC."""
import pathlib,json,gzip,hashlib,urllib.request,concurrent.futures,time
import pandas as pd
import numpy as np
import prepare
ROOT=pathlib.Path(__file__).resolve().parent
def main():
 data=ROOT/'data';data.mkdir(exist_ok=True);cache=ROOT/'primary_api';cache.mkdir(exist_ok=True)
 start=int(prepare.START.timestamp()/60);end=int(prepare.END.timestamp()/60)
 assert start==25771680 and end>start
 buckets=list(range(start//1000*1000,end,1000))
 def get(t):
  url=f'https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60&limit=1000&start={t*60}&end={(t+999)*60}';dest=cache/f'{t}.json.gz';error=''
  assert 1546200000<=t*60<1776000000
  for attempt in range(4):
   try:
    if dest.exists():
     with gzip.open(dest,'rb') as f:raw=f.read()
    else:
     with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RizanHistoricalResearch/1.0'}),timeout=45) as r:raw=r.read()
     with gzip.open(dest,'wb') as f:f.write(raw)
    rows=json.loads(raw)['data']['ohlc'];v=[]
    for x in rows:
     m=int(x['timestamp'])//60
     if t<=m<t+1000 and start<=m<end:
      o,h,l,c=[float(x[k]) for k in ['open','high','low','close']];vol=float(x.get('volume',0))
      if not np.isfinite([o,h,l,c,vol]).all() or l<=0 or vol<0 or l>min(o,c) or h<max(o,c):raise ValueError('BAD_PRIMARY_OHLC')
      v.append((m,o,h,l,c,vol))
    return v,{'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'rows':len(v),'status':'OK','bucket':t}
   except Exception as e:
    error=str(e)
    if attempt<3:time.sleep(1+attempt)
  return [],{'url':url,'status':'UNRESOLVED','error':error,'bucket':t}
 vals=[];proof=[]
 with concurrent.futures.ThreadPoolExecutor(10) as pool:
  for i,(v,p) in enumerate(pool.map(get,buckets)):
   vals.extend(v);proof.append(p)
   if (i+1)%100==0:print('PRIMARY_FULL',i+1,'/',len(buckets),'rows',len(vals),flush=True)
 q=pd.DataFrame(vals,columns=['minute','open','high','low','close','volume']);del vals
 if q.minute.duplicated().any():raise ValueError('DUPLICATE_PRIMARY_TIMESTAMP')
 q.index=pd.DatetimeIndex(pd.to_datetime(q.minute,unit='m',utc=True)).as_unit('ns');q=q.sort_index()
 oldpath=data/'BTCUSD_M1.csv';comparison={}
 if oldpath.exists():
  old=pd.read_csv(oldpath,index_col=0,parse_dates=True);old.index=pd.to_datetime(old.index,utc=True).as_unit('ns');old=old.add_suffix('_old');both=old.join(q[['open','high','low','close']],how='inner')
  err=np.max(np.array([np.abs(both[c+'_old']-both[c]) for c in ['open','high','low','close']]),axis=0)
  changed=both.loc[err>1e-6];changed.to_csv(data/'BTCUSD_SOURCE_DIFFERENCES.csv',index_label='timestamp')
  comparison={'overlap_rows':len(both),'exact_ohlc_rows':int((err<=1e-6).sum()),'different_ohlc_rows':len(changed),'max_price_difference':float(err.max()) if len(err) else 0.,'timestamps_only_old':len(old.index.difference(q.index)),'timestamps_only_official':len(q.index.difference(old.index))}
  (data/'BTCUSD_SOURCE_COMPARISON.json').write_text(json.dumps(comparison,indent=2))
  old.to_csv(data/'BTCUSD_PRE_OFFICIAL_FULL.csv.gz',compression='gzip')
 q[['volume']].to_csv(data/'BTCUSD_OFFICIAL_VOLUME.csv.gz',compression='gzip')
 provenance={'source':'OFFICIAL_BITSTAMP_HISTORICAL_OHLC_API','manifest':'BTCUSD_OFFICIAL_FULL_PROVENANCE.json','no_locally_synthesized_prices':True,'zero_volume_provider_candles':int((q.volume==0).sum()),'quote_type':'Exchange trade OHLC, not broker bid/ask','policy':'Primary exchange feed precedence for entire input, determined before financial replay. Original research input retained separately.'}
 prepare.audit('BTCUSD',q[['open','high','low','close']],provenance)
 expected=end-start
 summary={'first':str(q.index[0]) if len(q) else None,'last':str(q.index[-1]) if len(q) else None,'expected_calendar_minutes':expected,'rows':len(q),'missing_minutes':expected-len(q),'zero_volume_provider_candles':int((q.volume==0).sum()),'requests':proof,'source_comparison':comparison,'status':'OFFICIAL_OHLC_COMPLETE' if len(q)==expected else 'OFFICIAL_OHLC_PARTIAL'}
 (data/'BTCUSD_OFFICIAL_FULL_PROVENANCE.json').write_text(json.dumps(summary,indent=2));print({k:v for k,v in summary.items() if k!='requests'},flush=True)
if __name__=='__main__':main()

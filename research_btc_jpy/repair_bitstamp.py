"""Repair missing/conflicting candles only from timestamped official Bitstamp OHLC.
No local OHLC interpolation. Existing non-conflicting values are never replaced.
"""
import pathlib,json,urllib.request,hashlib,gzip,concurrent.futures,time,shutil
import pandas as pd
import numpy as np
import prepare
ROOT=pathlib.Path(__file__).resolve().parent
def main():
    d=ROOT/'data';path=d/'BTCUSD_M1.csv';q=pd.read_csv(path,index_col=0,parse_dates=True);q.index=pd.to_datetime(q.index,utc=True).as_unit('ns')
    old=json.loads((d/'BTCUSD_AUDIT.json').read_text());shutil.copy2(d/'BTCUSD_AUDIT.json',d/'BTCUSD_PRE_PRIMARY_API_AUDIT.json')
    allminutes=pd.date_range(prepare.START,prepare.END-pd.Timedelta(minutes=1),freq='min').as_unit('ns')
    missing=allminutes.difference(q.index);requested=set(missing.asi8//60000000000)
    buckets=sorted({int(x)//1000*1000 for x in requested});cache=ROOT/'primary_api';cache.mkdir(exist_ok=True)
    def fetch(start):
        url=f'https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60&limit=1000&start={start*60}&end={(start+999)*60}'
        dest=cache/f'{start}.json.gz';err=''
        for attempt in range(4):
            try:
                if dest.exists():
                    with gzip.open(dest,'rb') as f:raw=f.read()
                else:
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RizanHistoricalResearch/1.0'}),timeout=45) as r:raw=r.read()
                    with gzip.open(dest,'wb') as f:f.write(raw)
                data=json.loads(raw)['data']['ohlc'];vals=[]
                for a in data:
                    m=int(a['timestamp'])//60
                    if start<=m<start+1000:
                        o,h,l,c=[float(a[k]) for k in ['open','high','low','close']]
                        if not np.isfinite([o,h,l,c]).all() or l<=0 or l>min(o,c) or h<max(o,c):raise ValueError('INVALID_PRIMARY_OHLC')
                        vals.append((m,o,h,l,c,float(a.get('volume',0))))
                return vals,{'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'rows':len(vals),'bucket':start,'status':'OK'}
            except Exception as e:
                err=str(e)
                if attempt<3:time.sleep(1+attempt)
        return [],{'url':url,'bucket':start,'status':'UNRESOLVED','error':err}
    added=[];proof=[];overlap_exact=0;overlap_diff=0;done=0;existing={int(k):tuple(v) for k,v in zip(q.index.asi8//60000000000,q.to_numpy())}
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for vals,p in ex.map(fetch,buckets):
            proof.append(p);done+=1
            for m,o,h,l,c,volume in vals:
                if m in requested:added.append((m,o,h,l,c,volume))
                elif m in existing:
                    if np.max(np.abs(np.array(existing[m])-np.array([o,h,l,c])))<=1e-6:overlap_exact+=1
                    else:overlap_diff+=1
            if done%50==0:print('PRIMARY_API',done,'/',len(buckets),'recovered',len(added),flush=True)
    x=pd.DataFrame(added,columns=['minute','open','high','low','close','volume']);x=x.drop_duplicates('minute');x.index=pd.to_datetime(x.minute,unit='m',utc=True)
    x.to_csv(d/'BTCUSD_PRIMARY_API_ADDITIONS.csv',index_label='timestamp')
    new=pd.concat([q,x[['open','high','low','close']]])
    provenance={'original':old['source'],'primary_api_manifest':'BTCUSD_PRIMARY_API_PROVENANCE.json','policy':'Only missing and quarantined UTC timestamps restored; no original non-conflicting OHLC changed; primary API zero-volume candles retained as provider published, not locally interpolated.'}
    prepare.audit('BTCUSD',new,provenance)
    audit=json.loads((d/'BTCUSD_AUDIT.json').read_text());audit['original_quarantined_conflicts']=old['conflicting_timestamps_quarantined'];audit['identical_duplicate_rows_removed']=old['identical_duplicate_rows_removed'];audit['primary_api_repaired_count']=len(x)
    (d/'BTCUSD_AUDIT.json').write_text(json.dumps(audit,indent=2))
    summary={'requested_missing_minutes':len(missing),'recovered_minutes':len(x),'remaining_missing_minutes':len(missing)-len(x),'primary_zero_volume_added':int((x.volume==0).sum()),'overlap_exact':overlap_exact,'overlap_different':overlap_diff,'existing_prices_replaced':0,'requests':proof,'data_status':'PARTIAL_NO_HISTORICAL_BID_ASK_OR_BROKER_CONTRACT'}
    (d/'BTCUSD_PRIMARY_API_PROVENANCE.json').write_text(json.dumps(summary,indent=2));print({k:v for k,v in summary.items() if k!='requests'},flush=True)
if __name__=='__main__':main()

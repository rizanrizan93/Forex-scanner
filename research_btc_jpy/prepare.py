import argparse, pathlib, hashlib, json, urllib.request, concurrent.futures, gzip, shutil, time
import pandas as pd
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parent
START=pd.Timestamp('2019-01-01',tz='UTC'); END=pd.Timestamp('2026-04-01',tz='UTC')
def get(y):
    url=f'https://www.cryptodatadownload.com/cdd/Bitstamp_BTCUSD_{y}_minute.csv'
    dest=ROOT/'raw'/f'Bitstamp_BTCUSD_{y}_minute.csv.gz';dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        with gzip.open(dest,'rb') as f: raw=f.read()
    else:
        for retry in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=90) as r:raw=r.read()
                break
            except Exception:
                if retry==3:raise
                time.sleep(2)
        with gzip.open(dest,'wb') as f:f.write(raw)
    import io
    df=pd.read_csv(io.BytesIO(raw),skiprows=1)
    ts=pd.to_datetime(df['date'],utc=True)
    df.index=ts
    # Some nominal yearly files extend into the following year. Own-year rule
    # is fixed before strategy research and never chooses the best price.
    own=(ts.dt.year==y)
    out=df.loc[((ts>=START)&(ts<END)&own).to_numpy(),['open','high','low','close']].copy()
    return out,{'url':url,'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),'raw_rows':len(df),'outside_nominal_year_excluded':int((~own).sum()),'selected_rows':len(out),'merge_rule':'Use only timestamps within nominal file year; reject duplicates within resulting input.'}
def audit(symbol,df,provenance):
    df=df.sort_index()
    (ROOT/'data').mkdir(exist_ok=True)
    dup=df[df.index.duplicated(False)]
    conflicts=[];identical_removed=0
    if len(dup):
        different=dup.groupby(level=0).nunique().gt(1).any(axis=1)
        conflicts=list(different[different].index)
        if conflicts:
            df.loc[df.index.isin(conflicts)].to_csv(ROOT/'data'/f'{symbol}_QUARANTINED_CONFLICTS.csv')
            df=df.loc[~df.index.isin(conflicts)]
        identical_removed=int(df.index.duplicated().sum())
        df=df.loc[~df.index.duplicated(keep='first')]
    if df.index.duplicated().any():raise ValueError('duplicate timestamps '+symbol)
    v=df.to_numpy(dtype=float)
    if not np.isfinite(v).all() or (v<=0).any() or (v[:,1]<v[:,[0,2,3]].max(axis=1)).any() or (v[:,2]>v[:,[0,1,3]].min(axis=1)).any():raise ValueError('OHLC invalid '+symbol)
    d=np.diff(df.index.asi8)//60000000000
    gaps=[{'after':str(df.index[i]),'before':str(df.index[i+1]),'missing_minutes':int(d[i]-1)} for i in np.where(d>1)[0]]
    (ROOT/'data').mkdir(exist_ok=True)
    out=ROOT/'data'/f'{symbol}_M1.csv'
    df.index.name='timestamp';df.to_csv(out,date_format='%Y-%m-%d %H:%M:%S',float_format='%.8f')
    meta={'symbol':symbol,'first':str(df.index[0]),'last':str(df.index[-1]),'rows':len(df),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'source':provenance,'identical_duplicate_rows_removed':identical_removed,'conflicting_timestamps_quarantined':[str(x) for x in conflicts],'gaps':gaps,'gap_count':len(gaps),'flat_bars':int((v[:,1]==v[:,2]).sum()),'synthetic_ticks':False,'status':'PARTIAL_CANDLE_DATA_NO_BID_ASK','months':df.resample('MS').size().astype(int).to_dict()}
    meta['months']={str(k):v for k,v in meta['months'].items()}
    (ROOT/'data'/f'{symbol}_AUDIT.json').write_text(json.dumps(meta,indent=2))
    print(symbol,len(df),str(df.index[0]),str(df.index[-1]),'gap_count',len(gaps),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('symbol');p.add_argument('--usdjpy');a=p.parse_args()
    if a.symbol=='BTCUSD':
        results=list(concurrent.futures.ThreadPoolExecutor(4).map(get,range(2019,2027)))
        audit('BTCUSD',pd.concat([x[0] for x in results]),[x[1] for x in results])
    else:
        path=pathlib.Path(a.usdjpy);df=pd.read_csv(path)
        ts=pd.to_datetime(df.iloc[:,0],utc=True);df.index=ts
        df=df.iloc[:,1:5];df.columns=['open','high','low','close']
        df=df.loc[((ts>=START)&(ts<END)).to_numpy()]
        audit('USDJPY',df,{'artifact_run':39176779912,'artifact_id':12154458532,'archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'timezone':'Existing archive UTC; HistData EST-no-DST +5h normalization, not independently tick verified.'})
if __name__=='__main__':main()

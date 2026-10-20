"""Actual L2 and trade tape, sampled causally for research only."""
from pathlib import Path
import json,zipfile,time,concurrent.futures,gzip
import orjson,numpy as np,pandas as pd
from book_adapter import Book
ROOT=Path(__file__).resolve().parent

def prepare_book(day):
    out=ROOT/'derived'/f'{day}_book.npz';audit=out.with_suffix('.json')
    if out.exists() and audit.exists():return json.loads(audit.read_text())
    src=ROOT/'data'/f'{day}_BTCUSDT_ob500.data.zip'
    start=int(np.datetime64(day,'ms').astype('int64'));end=start+86_400_000;grid=start
    rows=[];book=Book();n=bad=regress=0;last=-1;t0=time.time()
    with zipfile.ZipFile(src) as z:
        assert len(z.namelist())==1
        with z.open(z.namelist()[0]) as f:
            for raw in f:
                m=orjson.loads(raw);t=int(m['ts'])
                if t<last:regress+=1
                while grid<min(t,end):
                    s=book.sample(grid);rows.append(s if s else (np.nan,)*5);bad+=int(s is None);grid+=1000
                book.apply(m);last=max(last,t);n+=1
        while grid<end:
            s=book.sample(grid);rows.append(s if s else (np.nan,)*5);bad+=int(s is None);grid+=1000
    ts=np.arange(start,end,1000,dtype=np.int64)
    assert len(rows)==len(ts)
    np.savez_compressed(out,exchange_ms=ts,available_ms=ts+1000,quotes=np.asarray(rows))
    r={'day':day,'messages':n,'invalid_seconds':bad,'timestamp_regressions':regress,'resets':book.resets,
       'zip_crc_full_read':True,'sample_seconds':len(rows),'book_publication_latency_assumption_ms':1000,
       'seconds':round(time.time()-t0,1)}
    audit.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True);return r

def prepare_trades(day):
    src=ROOT/'data'/f'{day}_BTCUSDT_trades.csv.gz';out=ROOT/'derived'/f'{day}_trades.npz'
    f=pd.read_csv(src,compression='gzip',dtype={'id':'string'})
    assert set(f.exchange)=={'bybit'} and set(f.symbol)=={'BTCUSDT'}
    raw_n=len(f);dupes=int(f.id.duplicated().sum());f=f.drop_duplicates('id',keep='first')
    unknown=int((~f.side.isin(['buy','sell'])).sum())
    assert unknown==0 and (f.amount>0).all() and (f.price>0).all()
    # Arrival time matters: never expose a late trade at its earlier exchange time.
    available=np.maximum(f.timestamp.to_numpy(np.int64),f.local_timestamp.to_numpy(np.int64))
    order=np.argsort(available,kind='stable')
    np.savez_compressed(out,available_us=available[order],exchange_us=f.timestamp.to_numpy(np.int64)[order],
                        price=f.price.to_numpy(float)[order],amount=f.amount.to_numpy(float)[order],
                        side=np.where(f.side.to_numpy()[order]=='buy',1,-1).astype(np.int8))
    lag=(f.local_timestamp-f.timestamp)/1000
    r={'day':day,'trade_rows_raw':raw_n,'trade_rows_unique':len(f),'duplicate_ids_removed':dupes,
       'unknown_sides':unknown,'side_semantics':'liquidity taker side per Tardis schema',
       'arrival_minus_exchange_ms_median':float(lag.median()),'arrival_minus_exchange_ms_p99':float(lag.quantile(.99)),
       'negative_arrival_lag_n':int((lag<0).sum()),'gzip_full_read':True}
    out.with_suffix('.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True);return r

if __name__=='__main__':
    cfg=json.loads((ROOT/'LOCKED_PROTOCOL.json').read_text())
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as ex:
        rows=list(ex.map(prepare_book,cfg['all_book_days']))
    trades=[prepare_trades(d) for d in cfg['sample_days']]
    (ROOT/'DATA_QUALITY.json').write_text(json.dumps({'books':rows,'trades':trades},indent=2)+'\n')

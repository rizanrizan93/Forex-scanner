"""Read-only Dukascopy BID+ASK M1 validator. Never treats M1 as native ticks."""
import argparse
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

COLS=['timestamp','open','high','low','close']

def read_quotes(path,side):
    a=pd.read_csv(path,low_memory=False)
    if not set(COLS).issubset(a.columns):raise ValueError(f'{path}: columns missing')
    t=a.timestamp
    at=(pd.to_datetime(t,unit='ms',utc=True,errors='coerce')
        if pd.api.types.is_numeric_dtype(t)
        else pd.to_datetime(t,utc=True,errors='coerce'))
    if at.isna().any():raise ValueError('Bad timestamps')
    a=a.assign(timestamp=at).sort_values('timestamp')
    if a.timestamp.duplicated().any():raise ValueError('Duplicate timestamp')
    for c in COLS[1:]:a[c]=pd.to_numeric(a[c],errors='raise')
    if not np.isfinite(a[COLS[1:]]).all().all() or not (a[COLS[1:]]>0).all().all():
        raise ValueError('Bad OHLC values')
    if ((a.high<a[['open','close','low']].max(axis=1))|
        (a.low>a[['open','close','high']].min(axis=1))).any():
        raise ValueError('Invalid OHLC geometry')
    return a[COLS].rename(columns={c:f'{side}_{c}' for c in COLS[1:]})

def normalize_bid_ask(bid_path,ask_path,out_path,start,end):
    bid_path=Path(bid_path);ask_path=Path(ask_path);out_path=Path(out_path)
    b=read_quotes(bid_path,'bid');a=read_quotes(ask_path,'ask')
    n_b,n_a=len(b),len(a)
    matched=b.merge(a,on='timestamp',how='inner',validate='one_to_one')
    if matched.empty:raise ValueError('No matching M1 BID/ASK timestamps')
    start_ts=pd.Timestamp(start,tz='UTC');end_ts=pd.Timestamp(end,tz='UTC')
    m=matched.loc[(matched.timestamp>=start_ts)&(matched.timestamp<end_ts)].copy()
    if m.empty:raise ValueError('No M1 in requested holdout interval')
    m['spread_open']=m.ask_open-m.bid_open
    m['spread_close']=m.ask_close-m.bid_close
    m['spread']=m.spread_open
    if ((m.spread_open<0)|(m.spread_close<0)).any():raise ValueError('Negative BID/ASK spread')
    if not (m.spread_open>0).any():raise ValueError('No genuine quote spread')
    # Do not use different-minute-bar extrema to infer synchronous ask/bid spreads.
    m['open']=m.bid_open;m['high']=m.bid_high;m['low']=m.bid_low;m['close']=m.bid_close
    ordered=['timestamp','open','high','low','close','spread','bid_open','bid_high','bid_low','bid_close','ask_open','ask_high','ask_low','ask_close','spread_open','spread_close']
    m=m[ordered]
    if m.timestamp.duplicated().any():raise ValueError('Duplicate output minute')
    out_path.parent.mkdir(parents=True,exist_ok=True)
    m.to_csv(out_path,index=False)
    gaps=m.timestamp.diff().dt.total_seconds().dropna().to_numpy()/60
    total_days=max(1,len(pd.date_range(start_ts,end_ts-pd.Timedelta(days=1),freq='D')))
    manifest={
       'source':'DUKASCOPY_MIN_1_BID_ASK',
       'kind':'M1_CANDLE_NOT_NATIVE_TICKS',
       'requested_start':start,'requested_end_exclusive':end,
       'span_start_utc':m.timestamp.min().isoformat(),
       'span_last_utc':m.timestamp.max().isoformat(),
       'rows':int(len(m)),'bid_rows':n_b,'ask_rows':n_a,
       'matched_rows':int(len(matched)),
       'mean_spread_open':float(m.spread_open.mean()),
       'p99_spread_open':float(m.spread_open.quantile(.99)),
       'gap_count_gt_60m':int((gaps>60).sum()),
       'files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (bid_path,ask_path)},
       'output_sha256':hashlib.sha256(out_path.read_bytes()).hexdigest(),
       'data_ready':bool(len(m)>=1440 and m.timestamp.min()<=start_ts+pd.Timedelta(days=5) and
          m.timestamp.max()>=end_ts-pd.Timedelta(days=5) and
          len(m)/(total_days*1440)>=.30 and
          abs(n_b-n_a)/max(n_b,n_a)<.03),
       'limitations':'Approximate quote spread at M1 open; not synchronized tick bid/ask or FP Markets fills.'
    }
    return manifest

def main():
    p=argparse.ArgumentParser()
    for k in ('bid','ask','out','start','end'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    m=normalize_bid_ask(a.bid,a.ask,a.out,a.start,a.end)
    Path(a.out).with_suffix('.quality.json').write_text(json.dumps(m,indent=2))
    print(json.dumps(m,indent=2),flush=True)
    if not m['data_ready']:sys.exit('Not enough OOS data; prohibit performance claims')
if __name__=='__main__':main()

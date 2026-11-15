"""Audit every tick; preserve UTC millisecond timestamps and executable sides."""
import pathlib,json,hashlib,datetime
import numpy as np,pandas as pd,pyarrow.parquet as pq
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load_ticks(p):
 table=pq.read_table(p,columns=['timestamp','bid','ask']);meta=table.schema.metadata or {}
 point=float(meta.get(b'point',b'1000'))
 if meta.get(b'symbol')!=b'XAUUSD' or point!=1000:raise ValueError('Unexpected XAU instrument metadata')
 ts=table['timestamp'].cast('int64').to_numpy().astype(np.int64)
 bid=table['bid'].to_numpy().astype(np.float64)/point;ask=table['ask'].to_numpy().astype(np.float64)/point
 return ts,bid,ask
def build(p):
 ts,bid,ask=load_ticks(p)
 finite=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>=bid)
 order=int(np.sum(np.diff(ts)<0));duplicate=int(np.sum((np.diff(ts)==0)&(np.diff(bid)==0)&(np.diff(ask)==0)))
 if order:raise ValueError('UNSORTED_TICKS '+p.name)
 audit={'file':p.name,'rows':len(ts),'first_utc':pd.Timestamp(int(ts[0]),unit='ms',tz='UTC').isoformat(),'last_utc':pd.Timestamp(int(ts[-1]),unit='ms',tz='UTC').isoformat(),'invalid_ticks':int((~finite).sum()),'timestamp_inversions':order,'adjacent_exact_duplicates':duplicate,'gaps_gt_5m':int((np.diff(ts)>300000).sum()),'spread_mean':float(np.mean(ask-bid)),'spread_p99':float(np.quantile(ask-bid,.99))}
 # Invalid/crossed quotes are rejected, not repaired. Reject affected bars later.
 ts,bid,ask=ts[finite],bid[finite],ask[finite]
 df=pd.DataFrame({'bid':bid,'ask':ask,'mid':(bid+ask)/2,'spread':ask-bid},index=pd.to_datetime(ts,unit='ms',utc=True))
 bars=df.resample('5min',closed='left',label='left').agg(open=('mid','first'),high=('mid','max'),low=('mid','min'),close=('mid','last'),bid_close=('bid','last'),ask_close=('ask','last'),spread=('spread','mean'),ticks=('mid','count'))
 bars['first_tick']=pd.Series(ts,index=df.index).resample('5min').first();bars['last_tick']=pd.Series(ts,index=df.index).resample('5min').last()
 bars['max_gap_ms']=pd.Series(np.r_[0,np.diff(ts)],index=df.index).resample('5min').max()
 audit['invalid_bars']=int(bars.close.isna().sum())
 return bars,audit
if __name__=='__main__':
 out=ROOT/'derived';out.mkdir(exist_ok=True);audits=[];parts=[]
 for p in sorted((ROOT/'data').glob('XAUUSD_*.parquet')):
  bars,audit=build(p);parts.append(bars);audits.append(audit);print(p.name,audit['rows'],flush=True)
 pd.concat(parts).sort_index().to_parquet(out/'xau_m5.parquet')
 (ROOT/'audit/tick_integrity.json').write_text(json.dumps(audits,indent=2))

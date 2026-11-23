"""Reconstruct only original EUR M5 breakout64 (base3) tape from exact input.

Math/record layout copied from the recovered original generator; no new seed
strategy. No macro timeline is synthesized: original seed and Mode=off do not
consume an external MacroDaily timeline. Source flags in XAU CSV are preserved.
"""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

EXPECTED='710f10ed97e709f48e284e79511981e4e85638deca6958a668908d6f418285c5'
DTYPE=np.dtype([('t','<i8'),('idx','<i4'),('symbol','<i4'),('side','<i4'),('trend','<i4'),('atr','<f8'),('anchor','<f8')])

def aggregate(m,tf):
    h=m.resample(f'{tf}min').agg({'open':'first','high':'max','low':'min','close':'last'})
    h['count']=m.close.resample(f'{tf}min').count();h=h.dropna()
    pc=h.close.shift().fillna(h.open)
    tr=pd.concat([h.high-h.low,(h.high-pc).abs(),(h.low-pc).abs()],axis=1).max(axis=1)
    h['atr']=tr.ewm(alpha=1/14,adjust=False).mean()
    return h

def prepare(source,out):
    source=Path(source);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(source.read_bytes()).hexdigest();assert digest==EXPECTED
    parts=[]
    for p in pd.read_csv(source,usecols=['timestamp','open','high','low','close'],chunksize=500000):
        p=p[p.timestamp>='2018-01-01']
        if len(p):parts.append(p)
    m=pd.concat(parts,ignore_index=True);del parts
    m.index=pd.to_datetime(m.pop('timestamp'),utc=True)
    assert m.index.is_monotonic_increasing and m.index.is_unique
    times=m.index.asi8//60_000_000_000
    higher={}
    for tf in (60,240):
        h=aggregate(m,tf)
        h['trend']=np.sign(h.close.ewm(span=20,adjust=False).mean()-h.close.ewm(span=80,adjust=False).mean())
        h.index+=pd.Timedelta(minutes=tf);higher[tf]=h[['trend','count']]
    h=aggregate(m,5);at=h.index+pd.Timedelta('5min');minutes=at.asi8//60_000_000_000
    pos=np.searchsorted(times,minutes);safe=np.minimum(pos,len(times)-1)
    exists=(pos<len(times))&(times[safe]==minutes)
    common=(h['count'].to_numpy()==5)&(at.year>=2019)&(at.dayofweek<5)&(at.hour<20)&exists&np.isfinite(h.atr.to_numpy())&(h.atr.to_numpy()>0)
    trends={}
    for tf,src in higher.items():
        j=src.index.get_indexer(at,method='pad');valid=j>=0;jj=np.maximum(j,0)
        age=(at.asi8-src.index.asi8[jj])/60e9
        valid&=(age>=0)&(age<=2*tf)&(src['count'].to_numpy()[jj]==tf)
        trends[tf]=np.where(valid,src.trend.to_numpy()[jj],0)
    hi=h.high.shift().rolling(64).max();lo=h.low.shift().rolling(64).min()
    tests=((h.close>hi+.05*h.atr)&(h.close>h.open),(h.close<lo-.05*h.atr)&(h.close<h.open))
    warm=np.arange(len(h))>=max(4*64,80);arrays=[]
    for side,test in zip((1,-1),tests):
        jj=np.flatnonzero(common&warm&test.to_numpy());a=np.zeros(len(jj),dtype=DTYPE)
        a['t']=minutes[jj];a['idx']=pos[jj];a['symbol']=0;a['side']=side
        a['atr']=h.atr.to_numpy()[jj]
        a['anchor']=h.low.to_numpy()[jj]-.05*a['atr'] if side==1 else h.high.to_numpy()[jj]+.05*a['atr']
        a['trend']=1+2*(trends[60][jj]==side)+4*(trends[240][jj]==side);arrays.append(a)
    tape=np.concatenate(arrays);tape.sort(order=['t','symbol']);assert DTYPE.itemsize==40
    dest=out/'base3_symbol0.bin';tape.tofile(dest)
    audit=dict(source_sha256=digest,source_rows=len(m),records=len(tape),record_bytes=40,
        output_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),original_tape_hash_unknown=True,
        reference_ledger_parity=False,first_minute=int(tape['t'][0]),last_minute=int(tape['t'][-1]))
    (out/'seed_reconstruction.json').write_text(json.dumps(audit,indent=2)+'\n')
    print('SEED_RECONSTRUCTED',json.dumps(audit),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();prepare(a.source,a.output)

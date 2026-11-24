"""Merge pinned yearly price chunks, then compute causal indicators continuously."""
import sys,json
from pathlib import Path
import numpy as np,pandas as pd
root=Path(sys.argv[1]).resolve();src=Path(sys.argv[2]);out=root/"data";out.mkdir(parents=True,exist_ok=True)
parts=[]
for year in range(2012,2027):
    p=src/f"continuous-xau-{year}"
    t=np.fromfile(p/"times.bin",dtype="<i8")
    v=np.fromfile(p/"bars.bin",dtype="<f8").reshape(-1,5)
    assert len(t)==len(v) and len(t)>100000
    assert np.all(np.diff(t)>0)
    ix=pd.to_datetime(t,unit="m",utc=True)
    assert ix[0].year==year and ix[-1].year==year
    parts.append(pd.DataFrame(v,columns=["open","high","low","close","spread"],index=ix))
m=pd.concat(parts);del parts
assert m.index.is_unique and m.index.is_monotonic_increasing
times=(m.index.asi8//60_000_000_000).astype("<i8")
times.tofile(out/"1_times.i64")
m[["open","high","low","close","spread"]].to_numpy(dtype="<f8").tofile(out/"1_m1.f64")
def agg(tf):
    h=m.resample(f"{tf}min").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    h["count"]=m.close.resample(f"{tf}min").count().reindex(h.index)
    p=h.close.shift().fillna(h.open)
    h["atr"]=pd.concat([h.high-h.low,(h.high-p).abs(),(h.low-p).abs()],axis=1).max(axis=1).ewm(alpha=1/14,adjust=False).mean()
    return h
higher={}
for tf in (60,240):
    h=agg(tf);h["trend"]=np.sign(h.close.ewm(span=20,adjust=False).mean()-h.close.ewm(span=80,adjust=False).mean())
    h["warm"]=np.arange(len(h))>=80
    h.index+=pd.Timedelta(minutes=tf);higher[tf]=h
dtype=np.dtype([("t","<i8"),("idx","<i4"),("symbol","<i4"),("side","<i4"),("trend","<i4"),("atr","<f8"),("anchor","<f8")])
for ti,tf in enumerate((5,15,60)):
    h=agg(tf);at=h.index+pd.Timedelta(minutes=tf);mins=at.asi8//60_000_000_000
    idx=np.searchsorted(times,mins);safe=np.minimum(idx,len(times)-1)
    common=(idx<len(times))&(times[safe]==mins)&(h["count"].to_numpy()==tf)&(at.dayofweek<5)&(at.hour<20)&(h.atr.to_numpy()>0)
    trend={}
    for ht,src in higher.items():
        j=src.index.get_indexer(at,method="pad");jj=np.maximum(j,0);age=(at.asi8-src.index.asi8[jj])/60e9
        valid=(j>=0)&(age>=0)&(age<=2*ht)&(src["count"].to_numpy()[jj]==ht)&src.warm.to_numpy()[jj]
        trend[ht]=np.where(valid,src.trend.to_numpy()[jj],0)
    for fam in range(3):
        for li,lb in enumerate((8,16,32,64)):
            a=h.atr;hi=h.high.shift().rolling(lb).max();lo=h.low.shift().rolling(lb).min()
            cp=(h.close-h.low)/(h.high-h.low).replace(0,np.nan)
            fast=h.close.ewm(span=lb,adjust=False).mean();slow=h.close.ewm(span=4*lb,adjust=False).mean()
            if fam==0:
                buy=(h.close>hi+.05*a)&(h.close>h.open);sell=(h.close<lo-.05*a)&(h.close<h.open)
            elif fam==1:
                buy=(h.low<lo)&(h.close>lo+.05*a)&(h.close>h.open)&(cp>=.65)
                sell=(h.high>hi)&(h.close<hi-.05*a)&(h.close<h.open)&(cp<=.35)
            else:
                buy=(fast>slow)&(h.low<=fast)&(h.close>fast)&(h.close>h.high.shift())&(h.close>h.open)
                sell=(fast<slow)&(h.high>=fast)&(h.close<fast)&(h.close<h.low.shift())&(h.close<h.open)
            rows=[]
            for side,cond in ((1,buy),(-1,sell)):
                j=np.flatnonzero(common&(np.arange(len(h))>=max(4*lb,80))&cond.to_numpy())
                v=np.zeros(len(j),dtype=dtype);v["t"]=mins[j];v["idx"]=idx[j];v["symbol"]=1;v["side"]=side;v["atr"]=a.to_numpy()[j]
                v["anchor"]=(h.low.to_numpy()[j]-.05*v["atr"]) if side==1 else (h.high.to_numpy()[j]+.05*v["atr"])
                v["trend"]=1+2*(trend[60][j]==side)+4*(trend[240][j]==side)
                rows.append(v)
            v=np.concatenate(rows);v.sort(order=["t","symbol"])
            v.tofile(out/f"base{ti*12+fam*4+li}_symbol1.bin")
(root/"provenance.json").write_text(json.dumps({"first":str(m.index[0]),"last":str(m.index[-1]),"rows":len(m),"exact_frozen":False,"continuous":True,"source_pin":"1d8e4c008fe177be455f6de05f5057ebdde901ae"},indent=2))

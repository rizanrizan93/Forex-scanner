"""Million-grid input preparation; no account access. Run: prepare.py INPUT_CSV OUTPUT [cutoff]."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd

BD=np.dtype([('o','<f8'),('h','<f8'),('l','<f8'),('c','<f8'),('sp','<f8'),('t','<i8'),('day','<i4'),('year','<i4'),('minute','<i2'),('dow','<i2')])
ED=np.dtype([('entry','<i4'),('touch','<i4'),('style','<i4'),('s','<i4'),('atr','<f8'),('level','<f8'),('trend','<i4')])
MIN=60_000_000_000

def bars(d,n):
    g=d.resample(f'{n}min',label='right',closed='left')
    f=g.agg({'open':'first','high':'max','low':'min','close':'last'})
    required=n if n<=5 else int(n*.9)
    f=f.loc[g.close.count()>=required]
    return f[f.index<=d.index[-1]+pd.Timedelta(minutes=1)].dropna()

def atr(f):
    p=f.close.shift(1)
    return pd.concat([f.high-f.low,(f.high-p).abs(),(f.low-p).abs()],axis=1).max(axis=1).ewm(alpha=1/14,adjust=False,min_periods=14).mean()

def mapped(s,t):
    i=np.searchsorted(s.index.asi8,t,side='right')-1
    x=s.to_numpy()[np.maximum(i,0)].astype(float);x[i<0]=np.nan
    return x

def direction(f):
    e20=f.close.ewm(span=20,adjust=False,min_periods=20).mean();e50=f.close.ewm(span=50,adjust=False,min_periods=50).mean()
    return pd.Series(np.where((e20>e20.shift(3))&(f.close>e50),1,np.where((e20<e20.shift(3))&(f.close<e50),-1,0)),index=f.index)

def events(d,trigger_minutes):
    f=bars(d,trigger_minutes);h=bars(d,60);h4=bars(d,240);t=d.index.asi8;t5=f.index.asi8;start=t5-trigger_minutes*MIN
    a=atr(h);ah=mapped(a,start);ae=mapped(a,t5)
    up=h.high.diff();dn=-h.low.diff();p=up.where((up>dn)&(up>0),0).ewm(alpha=1/14,adjust=False).mean();m=dn.where((dn>up)&(dn>0),0).ewm(alpha=1/14,adjust=False).mean()
    adx=(100*(p-m).abs()/(p+m).replace(0,np.nan)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    bh=mapped(direction(h),t5);b4=mapped(direction(h4),t5);ad=mapped(adx,t5)
    prev=np.r_[np.nan,f.close.to_numpy()[:-1]];hi=f.high.to_numpy();lo=f.low.to_numpy();cl=f.close.to_numpy()
    local=pd.to_datetime(start,utc=True).tz_convert('Asia/Jakarta');mins=local.hour.to_numpy()*60+local.minute.to_numpy();dates=(start//MIN+420)//1440;phase=np.where(mins<840,0,np.where(mins<1140,1,2))
    # This only uses observations preceding the trigger close, never future completeness.
    uninterrupted=pd.Series(np.r_[False,np.diff(t)==MIN],index=d.index).rolling(60,min_periods=60).min()
    ready=mapped(uninterrupted.shift(1),start)==1
    hage=start-mapped(pd.Series(h.index.asi8,index=h.index),start);h4age=start-mapped(pd.Series(h4.index.asi8,index=h4.index),start)
    valid=(local.year>=2019)&(local.dayofweek<5)&(mins>=420)&np.isfinite(ah)&(ah>0)&ready&(hage<=120*MIN)&(h4age<=480*MIN)
    all_events=[];counts=[]
    for st in range(8):
      arr=[]
      for s in [1,-1]:
        born=None;alive=np.ones(len(f),bool)
        if st<2:
            ema=h.close.ewm(span=20,adjust=False,min_periods=50).mean();lev=mapped(ema-s*(0 if st==0 else .25)*a,start)
        elif st<4:
            n=[12,24][st-2];channel=h.high.shift(1).rolling(n).max() if s==1 else h.low.shift(1).rolling(n).min()
            crossed=(h.close>channel)&(h.close.shift(1)<=channel) if s==1 else (h.close<channel)&(h.close.shift(1)>=channel)
            level=channel.where(crossed).ffill();at=pd.Series(h.index.asi8,index=h.index).where(crossed).ffill();lev=mapped(level,start);born=mapped(at,start);alive=(start-born>=0)&(start-born<=6*60*MIN)
        elif st<6:
            roll=h.low.rolling([6,12][st-4]).min() if s==1 else h.high.rolling([6,12][st-4]).max();lev=mapped(roll,start)
        else:
            bottom=h.high.shift(2) if s==1 else h.high;top=h.low if s==1 else h.low.shift(2)
            ok=(top-bottom>=.1*a)&(h.index.to_series().diff(2).dt.total_seconds()==7200)
            target=(top if s==1 else bottom) if st==6 else (top+bottom)/2
            level=target.where(ok).ffill();at=pd.Series(h.index.asi8,index=h.index).where(ok).ffill();lev=mapped(level,start);born=mapped(at,start);alive=(start-born>=0)&(start-born<=8*60*MIN)
        cross=(lo<=lev)&(prev>lev) if s==1 else (hi>=lev)&(prev<lev)
        ids=np.flatnonzero(cross&valid&alive&np.isfinite(lev));keys=born[ids] if born is not None else dates[ids]*3+phase[ids]
        _,first=np.unique(keys,return_index=True)
        for i in ids[np.sort(first)]:
          for k in range(i,min(i+max(1,10//trigger_minutes),len(f))):
            if t5[k]!=t5[i]+(k-i)*trigger_minutes*MIN:break
            if s*(cl[k]-lev[i])<=0:continue
            j=int(np.searchsorted(t,t5[k]));touch=int(np.searchsorted(t,start[i]))
            if j>=len(d) or t[j]!=t5[k] or not np.isfinite(ae[k]) or ae[k]<=0:break
            trend=(1 if bh[k]==s else 0)|(2 if bh[k]==s and b4[k]==s else 0)|(4 if bh[k]==s and b4[k]==s and ad[k]>=20 else 0)|(8 if bh[k]==s and b4[k]==s and ad[k]>=30 else 0)
            arr.append((j,touch,st,s,float(ae[k]),float(lev[i]),trend));break
      ev=np.array(arr,dtype=ED);ev.sort(order=['entry','touch','s']);all_events.append(ev);counts.append({'style':st,'events':len(ev)})
      pass
    out=np.concatenate(all_events);out.sort(order=['style','entry','touch','s'])
    return out,h,counts


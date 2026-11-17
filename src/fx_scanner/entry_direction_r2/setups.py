"""Causal entry universe for directional research. No order/account operations."""
from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd
from . import base
from . import indicator as ip
MIN=base.MIN;BD=base.BD;ED=base.ED

def extra_events(d,trigger,ctx):
 f=base.bars(d,trigger);h=base.bars(d,60);h4=base.bars(d,240);t=d.index.asi8;end=f.index.asi8;start=end-trigger*MIN;a=base.atr(h);ae=base.mapped(a,end)
 local=pd.to_datetime(start,utc=True).tz_convert('Asia/Jakarta');mins=local.hour.to_numpy()*60+local.minute.to_numpy();dates=(start//MIN+420)//1440;phase=np.where(mins<840,0,np.where(mins<1140,1,2))
 uninterrupted=pd.Series(np.r_[False,np.diff(t)==MIN],index=d.index).rolling(60,min_periods=60).min();ready=base.mapped(uninterrupted.shift(1),start)==1
 hage=start-base.mapped(pd.Series(h.index.asi8,index=h.index),start);h4age=start-base.mapped(pd.Series(h4.index.asi8,index=h4.index),start)
 valid=(local.year>=2019)&(local.dayofweek<5)&(mins>=420)&np.isfinite(ae)&(ae>0)&ready&(hage<=120*MIN)&(h4age<=480*MIN)
 prev=np.r_[np.nan,f.close.to_numpy()[:-1]];hi=f.high.to_numpy();lo=f.low.to_numpy();cl=f.close.to_numpy();out=[]
 for family in range(8):
  for scale in range(4):
   upper,lower,squeeze=ip.levels(family,scale,d,ctx);arr=[];style=8+family*4+scale+(40 if trigger==5 else 0)
   for s in [1,-1]:
    level=base.mapped(lower if s==1 else upper,start) if family not in [4,7] else base.mapped(upper if s==1 else lower,start)
    regime=ip.regime_mask(family,scale,s,d,ctx);native=base.mapped(pd.Series(regime.astype(float),index=d.index),start)>0
    if squeeze is not None:native&=base.mapped(pd.Series(squeeze.astype(float),index=d.index),start)>0
    if family in [4,7]:cross=(hi>=level)&(prev<level) if s==1 else (lo<=level)&(prev>level)
    else:cross=(lo<=level)&(prev>level) if s==1 else (hi>=level)&(prev<level)
    # Freeze and consume the first observed touch before context/confirmation.
    ids=np.flatnonzero(cross&valid&np.isfinite(level));_,first=np.unique(dates[ids]*3+phase[ids],return_index=True)
    for i in ids[np.sort(first)]:
     if not native[i]:continue
     for k in range(i,min(i+max(1,10//trigger),len(f))):
      if end[k]!=end[i]+(k-i)*trigger*MIN:break
      if s*(cl[k]-level[i])<=0:continue
      j=int(np.searchsorted(t,end[k]));touch=int(np.searchsorted(t,start[i]))
      if j>=len(d) or t[j]!=end[k]:break
      arr.append((j,touch,style,s,float(ae[k]),float(level[i]),0));break
   ev=np.array(arr,dtype=ED);ev.sort(order=['entry','touch','s']);out.append(ev);pass
 return np.concatenate(out)



def generate(d):
 t=d.index.asi8;ctx=ip.context(d);all_events=[]
 for trigger in [1,5]:
  e,_,_=base.events(d,trigger);e['style']+=(40 if trigger==5 else 0);all_events.extend([e,extra_events(d,trigger,ctx)])
 ev=np.concatenate(all_events);ev.sort(order=['style','entry','touch','s'])
 h=base.bars(d,60);h4=base.bars(d,240);a=base.atr(h);up=h.high.diff();dn=-h.low.diff();p=up.where((up>dn)&(up>0),0).ewm(alpha=1/14,adjust=False).mean();m=dn.where((dn>up)&(dn>0),0).ewm(alpha=1/14,adjust=False).mean();adx=(100*(p-m).abs()/(p+m).replace(0,np.nan)).ewm(alpha=1/14,adjust=False,min_periods=14).mean();em=h.close.ewm(span=20,adjust=False,min_periods=20).mean()
 event_t=t[ev['entry']];bh=base.mapped(base.direction(h),event_t);b4=base.mapped(base.direction(h4),event_t);ad=base.mapped(adx,event_t);slope=base.mapped(np.sign(em-em.shift(3)),event_t);s=ev['s']
 ev['trend']=(bh==s).astype(np.int32)|(((bh==s)&(b4==s)).astype(np.int32)*2)|(((bh==s)&(b4==s)&(ad>=20)).astype(np.int32)*4)|(((bh==s)&(b4==s)&(ad>=30)).astype(np.int32)*8)|((slope==s).astype(np.int32)*16)|((ad<20).astype(np.int32)*32)
 return ev

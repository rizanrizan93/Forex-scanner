"""Frozen R4 zone/reaction and outcome primitives; R5 injects DXY/yield rules.
No EUR or dollar proxy fallback is part of this engine.
"""
import itertools
import numpy as np
import pandas as pd
from fx_scanner.manual_range_reclaim_r3 import bars,atr,adx,map_values
from research.zone_rebound.audit import wilson
MIN=60_000_000_000
TRIGGERS=['INSIDE_REJECT','PROX_RECLAIM','DISTAL_SWEEP','MICRO_SHIFT']


def entry_events(d,touch,mf,*,macros,mask_fn):
    """First trigger AND macro support within 15 minutes, never best future entry."""
    t=d.index.asi8;o,h,l,c=[d[k].to_numpy() for k in ('open','high','low','close')]
    base=touch.reset_index(drop=True);ii=base.i.to_numpy(dtype=int);s=base.side.to_numpy();lo=base.lo.to_numpy();hi=base.hi.to_numpy();a=base.atr_h1.to_numpy()
    prox=np.where(s==1,hi,lo);dist=np.where(s==1,lo,hi);mid=(lo+hi)/2
    valid=np.ones(len(base),bool);swept=np.zeros(len(base),bool);chosen={(tr,ma):np.zeros(len(base),bool) for tr in TRIGGERS for ma in macros};rows=[]
    for step in range(1,16):
        j=np.minimum(ii+step-1,len(d)-1);en=np.minimum(j+1,len(d)-1)
        valid &= (ii+step<len(d))&(t[en]-t[ii]==step*MIN)
        valid &= s*(c[j]-dist)>=-.25*a
        swept |= np.where(s==1,l[j]<lo,h[j]>hi)
        body=s*(c[j]-o[j])>0;span=np.maximum(h[j]-l[j],1e-9)
        wick=np.where(s==1,np.minimum(o[j],c[j])-l[j],h[j]-np.maximum(o[j],c[j]))/span
        near=(s*(o[en]-dist)>=-.25*a)&(s*(o[en]-prox)<=3)&(s*(o[en]-base.reference.to_numpy())>=-3)
        patterns={
          'INSIDE_REJECT':body&(wick>=.3)&(c[j]>=lo)&(c[j]<=hi)&(o[en]>=lo)&(o[en]<=hi),
          'PROX_RECLAIM':body&(wick>=.3)&(s*(c[j]-prox)>=0),
          'DISTAL_SWEEP':swept&body&(wick>=.3)&(s*(c[j]-mid)>=0),
          'MICRO_SHIFT':body&(s*(c[j]-mid)>=0)&np.where(s==1,c[j]>np.maximum(h[np.maximum(j-1,0)],h[np.maximum(j-2,0)]),c[j]<np.minimum(l[np.maximum(j-1,0)],l[np.maximum(j-2,0)]))&(j>=ii+2),
        }
        fields={k:v[en] for k,v in mf.items()}
        for tr,ma in itertools.product(TRIGGERS,macros):
            hit=valid&near&patterns[tr]&mask_fn(ma,fields,s)&~chosen[(tr,ma)]
            chosen[(tr,ma)]|=hit;ids=np.flatnonzero(hit)
            if not len(ids):continue
            q=base.iloc[ids].copy();q['source_idx']=ids;q['touch_i']=ii[ids];q['touch_ns']=t[ii[ids]]
            q['i']=en[ids];q['time_ns']=t[en[ids]];q['reference']=o[en[ids]];q['trigger']=tr;q['macro']=ma;q['wait_minutes']=step
            q['late']=s[ids]*(o[en[ids]]-base.reference.to_numpy()[ids]);q['spread']=d.spread.to_numpy()[en[ids]]
            for k,v in fields.items():q[k]=v[ids]
            rows.append(q)
    if not rows:return pd.DataFrame()
    return pd.concat(rows,ignore_index=True).sort_values(['time_ns','source_idx','trigger','macro'],kind='stable').reset_index(drop=True)

def context_events(d,e):
    t=e.time_ns.to_numpy();s=e.side.to_numpy();h=bars(d,60);a=atr(h);ema=h.close.ewm(span=20,adjust=False,min_periods=20).mean()
    e['atr_h1']=map_values(a,t);e['adx']=map_values(adx(h)[0],t);e['slope']=s*map_values((ema-ema.shift(3))/a,t)
    e['age_hours']=(e.time_ns-e.pub_ns)/MIN/60
    local=pd.to_datetime(t,utc=True).tz_convert('Asia/Jakarta');minute=local.hour*60+local.minute
    e['year']=local.year;e['day']=(t//MIN+420)//1440;e['phase']=np.where(minute<840,'ASIA',np.where(minute<1140,'LONDON','NEW_YORK'))
    return e.loc[(local.dayofweek<5)&(minute>=420)&(minute<1440)].reset_index(drop=True)

def outcomes(d,e,cost=False):
    """First passage from known M1 OPEN. Ties explicit; only pre-resolution gaps matter."""
    t=d.index.asi8;h=d.high.to_numpy();l=d.low.to_numpy();c=d.close.to_numpy();i=e.i.to_numpy(dtype=int);s=e.side.to_numpy();n=len(e)
    ref=e.reference.to_numpy()+s*(e.spread.to_numpy() if cost else 0)
    # 0 unresolved; 1 target; 2 adverse first; 3 same-candle ambiguity; 4 gap; 5 timeout
    states={3:np.zeros(n,dtype=np.int8),10:np.zeros(n,dtype=np.int8)};when={3:np.zeros(n,dtype=np.int16),10:np.zeros(n,dtype=np.int16)}
    mae={3:np.zeros(n),10:np.zeros(n)};mfe={15:np.zeros(n),60:np.zeros(n),240:np.zeros(n)};badmax={15:np.zeros(n),60:np.zeros(n),240:np.zeros(n)}
    complete=np.ones(n,bool);out={}
    for step in range(240):
        j=np.minimum(i+step,len(d)-1);good=(i+step<len(d))&(t[j]-t[i]==step*MIN);complete &= good
        favorable=np.where(s==1,h[j]-ref,ref-l[j]);adverse=np.where(s==1,ref-l[j],h[j]-ref)
        for target,hz in [(3,60),(10,240)]:
            if step>=hz:continue
            unresolved=states[target]==0;gap=unresolved&~complete;states[target][gap]=4;when[target][gap]=step
            active=unresolved&complete;mae[target]=np.maximum(mae[target],np.where(active,adverse,0))
            win=favorable>=target;stop=adverse>=target;hit=active&(win|stop)
            states[target][hit]=np.where((win&stop)[hit],3,np.where(win[hit],1,2));when[target][hit]=step+1
        for hz in (15,60,240):
            if step<hz:
                mfe[hz]=np.maximum(mfe[hz],favorable);badmax[hz]=np.maximum(badmax[hz],adverse)
            if step+1==hz:
                out[f'complete_{hz}']=complete.copy();out[f'mfe_{hz}']=np.where(complete,mfe[hz],np.nan);out[f'mae_{hz}']=np.where(complete,badmax[hz],np.nan)
                signed=s*(c[j]-ref);out[f'close_{hz}']=np.where(complete,signed,np.nan)
    for target in (3,10):
        states[target][states[target]==0]=5
        out[f'state{target}']=states[target];out[f'target_minutes{target}']=np.where(states[target]==1,when[target],np.nan)
        out[f'mae_before{target}']=np.where(states[target]==1,mae[target],np.nan)
    return out

def select(q,mask):
    ids=np.flatnonzero(mask);times=q.time_ns.to_numpy(dtype=np.int64);days=q.day.to_numpy(dtype=np.int64);last=-10**18;day=-1;count=0;out=[]
    for j in ids:
        if days[j]!=day:day=int(days[j]);count=0
        if times[j]-last<240*MIN or count>=2:continue
        out.append(j);last=int(times[j]);count+=1
    return np.asarray(out,dtype=int)

def metric(q,ix):
    z=q.iloc[ix];n=len(z);out={'n':n}
    for k in (3,10):
        counts={name:int((z[f'state{k}']==code).sum()) for code,name in [(1,'target'),(2,'adverse'),(3,'ambiguous'),(4,'gap'),(5,'timeout')]};w=counts['target']
        out[f'target{k}']={**counts,'rate_all':w/n if n else None,'wilson_low':wilson(w,n),'resolved_direction_rate':w/(w+counts['adverse']) if w+counts['adverse'] else None,'spread_rate_all':float((z[f'state{k}_spread']==1).mean()) if n else None,'median_minutes':float(z.loc[z[f'state{k}']==1,f'target_minutes{k}'].median()) if w else None}
    for hz in (15,60,240):
        v=z[f'close_{hz}'];valid=v.notna();nn=int(valid.sum());out[f'direction_close{hz}']={'valid':nn,'up':int((v>0).sum()),'down':int((v<0).sum()),'flat':int((v==0).sum()),'rate_positive':float((v[valid]>0).mean()) if nn else None,'spread_rate_positive':float((z.loc[valid,f'close_{hz}']-z.loc[valid,'spread']>0).mean()) if nn else None,'median_mfe':float(z[f'mfe_{hz}'].median()) if nn else None,'median_mae':float(z[f'mae_{hz}'].median()) if nn else None}
    out['median_wait']=float(z.wait_minutes.median()) if n else None;out['median_late']=float(z.late.median()) if n else None
    return out

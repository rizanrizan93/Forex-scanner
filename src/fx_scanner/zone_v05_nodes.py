"""Frozen V05 node geometry, ported verbatim from offline research definitions.
Only H1/H4 are needed for this selected source/target policy.
"""
import numpy as np
import pandas as pd
HOUR=3_600_000_000_000

def arr(q,key):
    return q[key].astype('int64').to_numpy() if key=='time' else q[key].to_numpy()

def nodes(qs,f):
    rows=[]
    for tf in [60,240]:
        q=qs[tf];ot,hi,lo,cl,aa,tt=[arr(q,k) for k in ['open','high','low','close','atr','time']]
        seen=set()
        maxs={n:pd.Series(hi).rolling(n).max().shift(1).to_numpy() for n in [8,12,20,24,48]}
        mins={n:pd.Series(lo).rolling(n).min().shift(1).to_numpy() for n in [8,12,20,24,48]}
        for k in range(60,len(q)):
            a=aa[k];d=1 if cl[k]>ot[k] else -1;strength=abs(cl[k]-ot[k])/a
            if strength>=.6:
                for lb in [8,20]:
                    bos=cl[k]>maxs[lb][k] if d==1 else cl[k]<mins[lb][k]
                    if not bos:continue
                    base=-1
                    for b in range(k-1,k-7,-1):
                        if d*(cl[b]-ot[b])<=0:base=b;break
                    if base<0:continue
                    for style in [0,1,2]:
                        key=(base,d,style,lb)
                        if key in seen:continue
                        zl=lo[base] if style<2 else min(ot[base],cl[base])
                        zh=hi[base] if style==0 else ot[base] if d==1 and style==1 else hi[base] if style==1 else max(ot[base],cl[base])
                        if d==-1 and style==1:zl=ot[base]
                        if zh-zl<.03*a or zh-zl>2*a or d*(cl[k]-(zh if d==1 else zl))<.1*a:continue
                        seen.add(key);rows.append((tt[k],zl,zh,d,tf,a,strength,0,style,lb,tt[base],True))
            # Three-candle gap: middle impulse and current completed outer candle.
            if strength>=.1 and abs(cl[k-1]-ot[k-1])>=.5*aa[k-1]:
                if lo[k]>hi[k-2]:gd=1;zl=hi[k-2];zh=lo[k]
                elif hi[k]<lo[k-2]:gd=-1;zl=hi[k];zh=lo[k-2]
                else:gd=0;zl=0.;zh=0.
                if gd and .05*a<=zh-zl<=1.5*a and gd*(cl[k]-(zh if gd==1 else zl))>=.05*a:
                    rows.append((tt[k],zl,zh,gd,tf,a,abs(cl[k-1]-ot[k-1])/a,1,0,3,tt[k-2],True))
            for lb in [12,24,48]:
                level=maxs[lb][k] if d==1 else mins[lb][k]
                crossed=d*(cl[k]-level)>.1*a and d*(cl[k-1]-level)<=0
                if crossed and strength>=.3:
                    rows.append((tt[k],level-.1*a,level+.1*a,d,tf,a,strength,3,0,lb,tt[k-1],True))
    # EMA pullbacks: registered ahead of return, H1 only, distinct levels.
    q=qs[60];tt=arr(q,'time');last={}
    for k in range(210,len(q)):
        a=q.atr.iloc[k];c=q.close.iloc[k]
        for span in [20,50]:
            level=q[f'ema{span}'].iloc[k];d=1 if c>level else -1;distance=d*(c-level)/a
            if distance<.5:continue
            key=(span,d)
            if key in last and abs(level-last[key])<.3*a:continue
            last[key]=level;rows.append((tt[k],level-.15*a,level+.15*a,d,60,a,distance,5,0,span,tt[k],True))
    # Previous UTC trading-day extremes, available only at day completion.
    day=f.resample('1D').agg(high=('high','max'),low=('low','min'),n=('close','size'))
    day=day[day.n>=1000]
    for dt,row in day.iterrows():
        when=(dt+pd.Timedelta(days=1)).value;k=np.searchsorted(tt,when,side='right')-1
        if k<30:continue
        a=q.atr.iloc[k];c=q.close.iloc[k]
        for d,level in [(1,row.low),(-1,row.high)]:
            rows.append((when,level-.1*a,level+.1*a,d,60,a,(row.high-row.low)/a,4,0,24,dt.value,d*(c-level)>.3*a))
    # Confirmed H1 pivots are target nodes, never backdated to pivot time.
    hi=arr(q,'high');lo=arr(q,'low');cl=arr(q,'close');aa=arr(q,'atr')
    for lag in [2,4]:
        seen=set()
        for k in range(50,len(q)):
            p=k-lag
            for d in [1,-1]:
                level=lo[p] if d==1 else hi[p]
                ok=level==min(lo[k-2*lag:k+1]) if d==1 else level==max(hi[k-2*lag:k+1])
                key=(d,level)
                if ok and key not in seen and d*(cl[k]-level)>=.5*aa[k]:
                    seen.add(key);rows.append((tt[k],level-.05*aa[k],level+.05*aa[k],d,60,aa[k],d*(cl[k]-level)/aa[k],6,0,lag,tt[p],False))
    z=pd.DataFrame(rows,columns=['formed_ns','low','high','direction','tf','atr','strength','family','style','lookback','base_ns','origin_eligible'])
    z=z.sort_values('formed_ns',kind='stable').reset_index(drop=True)
    # Breakers are born on the source close that invalidated their parent OB.
    cols=['formed_ns','low','high','direction','tf','atr','strength','family','style','lookback','base_ns','origin_eligible']
    breakers=[]
    buffers={tf:tuple(arr(qs[tf],key) for key in ['time','close','open','atr']) for tf in [60,240]}
    for row in z[z.family.eq(0)].itertuples(index=False):
        t,c,o,a=buffers[int(row.tf)]
        k=np.searchsorted(t,row.formed_ns,side='right');end=row.formed_ns+120*HOUR
        while k<len(t) and t[k]<=end:
            if row.direction*(c[k]-(row.low if row.direction==1 else row.high))<0:
                d=-row.direction;power=abs(c[k]-o[k])/a[k]
                if d*(c[k]-(row.high if d==1 else row.low))>.05*a[k] and power>=.3:
                    breakers.append((t[k],row.low,row.high,d,int(row.tf),a[k],power,2,int(row.style),int(row.lookback),row.formed_ns,True))
                break
            k+=1
    if breakers:z=pd.concat([z,pd.DataFrame(breakers,columns=cols)],ignore_index=True).sort_values('formed_ns',kind='stable').reset_index(drop=True)
    for col in ['formed_ns','direction','tf','family','style','lookback','base_ns']:z[col]=z[col].astype('int64')
    return z
